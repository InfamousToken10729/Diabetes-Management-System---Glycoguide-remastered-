import os
import subprocess
import requests
from typing import Dict, Any, Optional
from pathlib import Path
import config
import database

def get_current_git_commit() -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None

def check_for_github_update(repo_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks the configured GitHub repository for new commits.
    Returns status dict with update availability.
    """
    if not repo_url:
        prof = database.get_profile()
        repo_url = prof.get("github_repo") if prof else None

    if not repo_url:
        return {
            "has_update": False,
            "message": "No GitHub repository URL configured in Settings."
        }

    # Extract owner/repo from URL
    clean_url = repo_url.strip().rstrip("/")
    if "github.com/" in clean_url:
        parts = clean_url.split("github.com/")[1].split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1].replace(".git", "")
        else:
            return {"has_update": False, "message": "Invalid GitHub repository format."}
    else:
        return {"has_update": False, "message": "Invalid GitHub repository URL."}

    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "GlycoGuide-Remastered"}

    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            commits = resp.json()
            if commits and len(commits) > 0:
                latest_sha = commits[0].get("sha")
                commit_msg = commits[0].get("commit", {}).get("message", "New version available")
                commit_author = commits[0].get("commit", {}).get("author", {}).get("name", "Unknown")
                commit_date = commits[0].get("commit", {}).get("author", {}).get("date", "")

                current_sha = get_current_git_commit()

                has_update = (current_sha is not None and latest_sha != current_sha)
                return {
                    "has_update": has_update,
                    "latest_commit": latest_sha[:7] if latest_sha else None,
                    "current_commit": current_sha[:7] if current_sha else None,
                    "message": commit_msg.split("\n")[0],
                    "author": commit_author,
                    "date": commit_date,
                    "repo": f"{owner}/{repo}"
                }
        return {
            "has_update": False,
            "message": f"GitHub returned status {resp.status_code}"
        }
    except Exception as e:
        return {
            "has_update": False,
            "message": f"Could not connect to GitHub: {str(e)}"
        }

def perform_update() -> Dict[str, Any]:
    """
    Executes git pull to update application files.
    SQLite database in data/glycoguide.db is strictly preserved.
    """
    try:
        res = subprocess.run(
            ["git", "pull"],
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        if res.returncode == 0:
            return {
                "success": True,
                "output": res.stdout.strip(),
                "message": "Application updated successfully! Please refresh or restart."
            }
        else:
            return {
                "success": False,
                "output": res.stderr.strip(),
                "message": "Git pull failed. Check repository permissions."
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Update failed: {str(e)}"
        }
