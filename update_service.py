import os
import sys
import shutil
import sqlite3
import tempfile
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import requests

import config
import database


def parse_github_owner_repo(repo_url: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Parses owner/repo from HTTPS URLs, SSH git URLs, or 'owner/repo' shorthand.
    """
    if not repo_url:
        return None
    clean = repo_url.strip().rstrip("/")
    if not clean:
        return None

    # Handle SSH format: git@github.com:owner/repo.git
    if clean.startswith("git@github.com:"):
        path_part = clean.split("git@github.com:", 1)[1]
    elif "github.com/" in clean:
        path_part = clean.split("github.com/", 1)[1]
    elif "/" in clean and "://" not in clean and " " not in clean:
        path_part = clean
    else:
        return None

    parts = [p for p in path_part.split("/") if p]
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def get_configured_repo_url(repo_url: Optional[str] = None) -> str:
    url = (repo_url or "").strip().rstrip("/")
    if not url:
        prof = database.get_profile()
        url = ((prof.get("github_repo") if prof else "") or "").strip().rstrip("/")
    if not url or url in config.LEGACY_GITHUB_REPOS:
        return config.DEFAULT_GITHUB_REPO
    return url


def is_frozen_executable() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_git_checkout() -> bool:
    return (not is_frozen_executable()) and (config.BASE_DIR / ".git").exists()


def _run_git(args: list, timeout: int = 20) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", f"safe.directory={config.BASE_DIR}"] + args
    return subprocess.run(
        cmd,
        cwd=str(config.BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def get_current_git_commit() -> Optional[str]:
    if is_git_checkout():
        try:
            res = _run_git(["rev-parse", "HEAD"], timeout=5)
            if res.returncode == 0:
                sha = res.stdout.strip()
                if sha:
                    return sha
        except Exception:
            pass
    version_file = config.BASE_DIR / ".installed_version"
    if version_file.exists():
        try:
            sha = version_file.read_text(encoding="utf-8").strip()
            if sha:
                return sha
        except Exception:
            pass
    return None


def _get_git_ls_remote_head(https_git_url: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "ls-remote", https_git_url, "HEAD"],
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip().split()[0]
    except Exception:
        pass
    return None


def create_pre_update_backup() -> Optional[str]:
    """
    Creates a safe online SQLite backup before updating code files.
    """
    if not Path(config.DB_PATH).exists():
        return None
    try:
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = config.BACKUP_DIR / f"pre_update_{ts}.db"

        src = sqlite3.connect(str(config.DB_PATH), timeout=20.0)
        dst = sqlite3.connect(str(backup_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()

        # Keep only the 10 most recent pre-update backups
        pre_backups = sorted(
            config.BACKUP_DIR.glob("pre_update_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_file in pre_backups[10:]:
            try:
                old_file.unlink()
            except Exception:
                pass

        return str(backup_path)
    except Exception:
        return None


def check_for_github_update(repo_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks the configured GitHub repository for newer commits without false positives
    when local development commits are ahead or running a standalone executable.
    """
    effective_url = get_configured_repo_url(repo_url)
    parsed = parse_github_owner_repo(effective_url)
    if not parsed:
        return {
            "has_update": False,
            "up_to_date": False,
            "error": True,
            "message": "Invalid GitHub repository URL.",
        }

    owner, repo = parsed
    repo_slug = f"{owner}/{repo}"
    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GlycoGuide-Remastered",
    }

    current_sha = get_current_git_commit()
    latest_sha = None
    commit_msg = ""
    commit_author = ""
    commit_date = ""

    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            commits = resp.json()
            if commits and len(commits) > 0:
                latest_sha = commits[0].get("sha")
                commit_msg = commits[0].get("commit", {}).get("message", "New version available").split("\n")[0]
                commit_author = commits[0].get("commit", {}).get("author", {}).get("name", "Unknown")
                commit_date = commits[0].get("commit", {}).get("author", {}).get("date", "")
            else:
                return {
                    "has_update": False,
                    "up_to_date": True,
                    "error": False,
                    "repo": repo_slug,
                    "current_commit": current_sha[:7] if current_sha else None,
                    "message": "GitHub repository has no commits yet.",
                }
        elif resp.status_code == 409:
            return {
                "has_update": False,
                "up_to_date": True,
                "error": False,
                "repo": repo_slug,
                "current_commit": current_sha[:7] if current_sha else None,
                "message": "GitHub repository is empty (no commits yet).",
            }
        elif resp.status_code == 404:
            return {
                "has_update": False,
                "up_to_date": False,
                "error": True,
                "repo": repo_slug,
                "current_commit": current_sha[:7] if current_sha else None,
                "message": f"Repository '{repo_slug}' not found on GitHub (404).",
            }
        elif resp.status_code == 403:
            # Rate limit fallback using git ls-remote
            latest_sha = _get_git_ls_remote_head(f"https://github.com/{owner}/{repo}.git")
            if not latest_sha:
                return {
                    "has_update": False,
                    "up_to_date": False,
                    "error": True,
                    "repo": repo_slug,
                    "current_commit": current_sha[:7] if current_sha else None,
                    "message": "GitHub API rate limit reached. Try again later.",
                }
            commit_msg = "New commit available on GitHub"
        else:
            return {
                "has_update": False,
                "up_to_date": False,
                "error": True,
                "repo": repo_slug,
                "current_commit": current_sha[:7] if current_sha else None,
                "message": f"GitHub returned status {resp.status_code}.",
            }
    except Exception as e:
        return {
            "has_update": False,
            "up_to_date": False,
            "error": True,
            "repo": repo_slug,
            "current_commit": current_sha[:7] if current_sha else None,
            "message": f"Could not connect to GitHub: {str(e)}",
        }

    # Standalone frozen .exe cannot self-apply git updates
    if is_frozen_executable():
        return {
            "has_update": False,
            "up_to_date": True,
            "error": False,
            "is_frozen": True,
            "is_git_repo": False,
            "latest_commit": latest_sha[:7] if latest_sha else None,
            "current_commit": None,
            "repo": repo_slug,
            "message": f"Standalone .exe active (GitHub latest: {latest_sha[:7] if latest_sha else 'unknown'}).",
        }

    # Non-git install without recorded .installed_version marker
    if not current_sha:
        return {
            "has_update": False,
            "up_to_date": True,
            "error": False,
            "is_frozen": False,
            "is_git_repo": is_git_checkout(),
            "latest_commit": latest_sha[:7] if latest_sha else None,
            "current_commit": None,
            "repo": repo_slug,
            "message": f"Connected to {repo_slug} (latest commit: {latest_sha[:7] if latest_sha else 'unknown'}).",
        }

    if latest_sha == current_sha:
        return {
            "has_update": False,
            "up_to_date": True,
            "error": False,
            "is_frozen": False,
            "is_git_repo": is_git_checkout(),
            "latest_commit": latest_sha[:7],
            "current_commit": current_sha[:7],
            "message": "Your system is up-to-date!",
            "author": commit_author,
            "date": commit_date,
            "repo": repo_slug,
        }

    # Verify remote is genuinely ahead of current_sha (prevent false prompt on unpushed local commits)
    has_update = True
    try:
        cmp_url = f"https://api.github.com/repos/{owner}/{repo}/compare/{current_sha}...{latest_sha}"
        cmp_resp = requests.get(cmp_url, headers=headers, timeout=8)
        if cmp_resp.status_code == 200:
            cmp_data = cmp_resp.json()
            ahead_by = int(cmp_data.get("ahead_by", 0))
            has_update = ahead_by > 0
        elif cmp_resp.status_code == 404 and is_git_checkout():
            # Current local commit may not exist on GitHub yet; check git ancestor status locally
            anc = _run_git(["merge-base", "--is-ancestor", latest_sha, "HEAD"], timeout=5)
            if anc.returncode == 0:
                has_update = False
    except Exception:
        pass

    return {
        "has_update": has_update,
        "up_to_date": not has_update,
        "error": False,
        "is_frozen": False,
        "is_git_repo": is_git_checkout(),
        "latest_commit": latest_sha[:7] if latest_sha else None,
        "current_commit": current_sha[:7],
        "message": commit_msg if has_update else "Local version includes unpushed changes or is already current.",
        "author": commit_author,
        "date": commit_date,
        "repo": repo_slug,
    }


def _reinstall_requirements_if_needed() -> Tuple[bool, str]:
    req_file = config.BASE_DIR / "requirements.txt"
    if not req_file.exists():
        return True, ""
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
        if res.returncode == 0:
            return True, ""
        return False, res.stderr.strip()
    except Exception as e:
        return False, str(e)


def _restore_shell_permissions():
    if os.name == "nt":
        return
    for sh_name in ("install.sh", "update.sh", "backup.sh"):
        sh_path = config.BASE_DIR / sh_name
        if sh_path.exists():
            try:
                mode = sh_path.stat().st_mode
                os.chmod(sh_path, mode | 0o755)
            except Exception:
                pass


def _sync_from_zip(owner: str, repo: str) -> Dict[str, Any]:
    """
    Updates application source cleanly from GitHub archive zip for ZIP-downloaded installs.
    Strictly preserves data/, backups/, venv/, .venv/, env/.
    """
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "GlycoGuide-Remastered"}
    meta_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=10)
    default_branch = "main"
    if meta_resp.status_code == 200:
        default_branch = meta_resp.json().get("default_branch") or "main"

    commits_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}",
        headers=headers,
        timeout=10,
    )
    latest_sha = commits_resp.json().get("sha") if commits_resp.status_code == 200 else None

    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{default_branch}.zip"
    dl = requests.get(zip_url, headers={"User-Agent": "GlycoGuide-Remastered"}, timeout=45)
    if dl.status_code != 200:
        return {
            "success": False,
            "message": f"Failed to download update archive from GitHub (HTTP {dl.status_code}).",
        }

    preserve_top_dirs = {"data", "backups", "venv", ".venv", "env", ".git", "__pycache__"}
    tmp_dir = Path(tempfile.mkdtemp(prefix="glyco_update_"))
    try:
        zip_path = tmp_dir / "update.zip"
        zip_path.write_bytes(dl.content)
        extract_dir = (tmp_dir / "extracted").resolve()
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                target_path = (extract_dir / member.filename).resolve()
                if not str(target_path).startswith(str(extract_dir)):
                    raise ValueError("Unsafe path in update archive")
            zf.extractall(extract_dir)

        roots = [p for p in (tmp_dir / "extracted").iterdir() if p.is_dir()]
        if not roots:
            return {"success": False, "message": "Downloaded archive was empty."}
        src_root = roots[0]

        for item in src_root.iterdir():
            if item.name in preserve_top_dirs or item.name.endswith(".exe"):
                continue
            dest = config.BASE_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        if latest_sha:
            (config.BASE_DIR / ".installed_version").write_text(latest_sha, encoding="utf-8")

        return {
            "success": True,
            "output": f"Synced archive from {owner}/{repo}@{default_branch}",
            "message": "Application updated from GitHub archive! Local database safely preserved.",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def perform_update(repo_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Safely backs up the database, updates files via git pull (or GitHub archive fallback),
    updates pip dependencies, and triggers clean service restart when supported.
    """
    if is_frozen_executable():
        return {
            "success": False,
            "is_frozen": True,
            "restarting": False,
            "message": "Running standalone GlycoGuide.exe. Please download the latest release from GitHub or run from source.",
        }

    effective_url = get_configured_repo_url(repo_url)
    parsed = parse_github_owner_repo(effective_url)
    if not parsed:
        return {"success": False, "restarting": False, "message": "Invalid GitHub repository URL."}
    owner, repo = parsed
    expected_https_git = f"https://github.com/{owner}/{repo}.git"

    backup_path = create_pre_update_backup()

    try:
        if is_git_checkout():
            _run_git(["config", "core.fileMode", "false"], timeout=5)

            # Ensure origin targets configured repo if missing or using legacy v2 URL
            remote_res = _run_git(["remote", "get-url", "origin"], timeout=5)
            cur_origin = remote_res.stdout.strip() if remote_res.returncode == 0 else ""
            cur_parsed = parse_github_owner_repo(cur_origin)
            if not cur_origin:
                _run_git(["remote", "add", "origin", expected_https_git], timeout=5)
            elif cur_parsed != (owner, repo) or cur_origin.rstrip("/") in config.LEGACY_GITHUB_REPOS:
                _run_git(["remote", "set-url", "origin", expected_https_git], timeout=5)

            branch_res = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
            branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"
            if not branch or branch == "HEAD":
                branch = "main"

            pull_res = _run_git(["pull", "--ff-only"], timeout=45)
            if pull_res.returncode != 0:
                # Fallback if upstream tracking wasn't explicitly set yet
                pull_res = _run_git(["pull", "--ff-only", "origin", branch], timeout=45)

            if pull_res.returncode != 0:
                return {
                    "success": False,
                    "restarting": False,
                    "output": pull_res.stderr.strip() or pull_res.stdout.strip(),
                    "message": "Git pull failed cleanly without modifying your database. Run ./update.sh if local edits exist.",
                }
            output_text = pull_res.stdout.strip()
        else:
            zip_res = _sync_from_zip(owner, repo)
            if not zip_res.get("success"):
                zip_res["restarting"] = False
                return zip_res
            output_text = zip_res.get("output", "")

        _restore_shell_permissions()
        _reinstall_requirements_if_needed()

        managed_by = os.environ.get("GLYCO_MANAGED_BY", "").strip().lower()
        restarting = managed_by in ("systemd", "run_bat")

        return {
            "success": True,
            "restarting": restarting,
            "backup_path": backup_path,
            "output": output_text,
            "message": (
                "Application updated successfully! Restarting server now..."
                if restarting
                else "Application updated successfully! Refreshing interface..."
            ),
        }
    except Exception as e:
        return {
            "success": False,
            "restarting": False,
            "message": f"Update failed: {str(e)}",
        }
