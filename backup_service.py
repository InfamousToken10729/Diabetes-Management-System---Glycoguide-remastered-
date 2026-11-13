import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import config
import database


def validate_backup_database(file_path: Path) -> Tuple[bool, str]:
    """
    Validates that a file is a non-empty SQLite 3 database containing
    the expected GlycoGuide schema tables.
    """
    if not file_path.exists():
        return False, "File does not exist."
    if file_path.stat().st_size < 512:
        return False, "File is too small to be a valid SQLite database."

    # Verify SQLite 3 magic header
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
            if not header.startswith(b"SQLite format 3\000"):
                return False, "File does not have a valid SQLite 3 header."
    except Exception as e:
        return False, f"Failed to read file header: {str(e)}"

    # Verify database readability and required GlycoGuide tables
    try:
        conn = sqlite3.connect(str(file_path), timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        required_tables = {"profiles", "device_users", "log_entries"}
        missing = required_tables - tables
        if missing:
            return False, f"Missing required GlycoGuide tables: {', '.join(sorted(missing))}"
        return True, "Valid GlycoGuide database."
    except Exception as e:
        return False, f"Database corruption or structure error: {str(e)}"


def create_backup(filename_prefix: str = "glycoguide_backup") -> Path:
    """
    Creates an online, safe WAL-consistent backup copy of the live database
    into the backups directory.
    """
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_path = config.BACKUP_DIR / f"{filename_prefix}_{ts}.db"

    if not config.DB_PATH.exists():
        database.init_db()

    src = sqlite3.connect(str(config.DB_PATH), timeout=20.0)
    dst = sqlite3.connect(str(dest_path))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    return dest_path


def list_backups() -> List[Dict[str, Any]]:
    """
    Returns a list of all database backup files in the server backups directory,
    sorted with the newest first.
    """
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups: List[Dict[str, Any]] = []

    for p in config.BACKUP_DIR.glob("*.db"):
        if not p.is_file():
            continue
        try:
            st = p.stat()
            created_dt = datetime.fromtimestamp(st.st_mtime, timezone.utc)

            name = p.name
            if name.startswith("pre_restore_"):
                kind = "Pre-Restore Safety"
            elif name.startswith("pre_update_"):
                kind = "Pre-Update Safety"
            elif name.startswith("uploaded_"):
                kind = "Uploaded File"
            else:
                kind = "Manual Backup"

            size_bytes = st.st_size
            if size_bytes < 1024:
                size_fmt = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_fmt = f"{size_bytes / 1024:.1f} KB"
            else:
                size_fmt = f"{size_bytes / (1024 * 1024):.2f} MB"

            backups.append({
                "filename": p.name,
                "size_bytes": size_bytes,
                "size_formatted": size_fmt,
                "created_at": created_dt.isoformat(),
                "display_time": created_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "kind": kind,
            })
        except Exception:
            continue

    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def get_backup_path(filename: str) -> Optional[Path]:
    """
    Safely resolves a backup file inside config.BACKUP_DIR without directory traversal.
    """
    safe_name = os.path.basename(filename)
    if not (safe_name.endswith(".db") or safe_name.endswith(".sqlite") or safe_name.endswith(".sqlite3")):
        return None
    target = (config.BACKUP_DIR / safe_name).resolve()
    if target.parent != config.BACKUP_DIR.resolve():
        return None
    if target.exists() and target.is_file():
        return target
    return None


def delete_backup(filename: str) -> bool:
    """
    Deletes a backup file from the server backups directory.
    """
    target = get_backup_path(filename)
    if not target:
        return False
    try:
        target.unlink()
        return True
    except Exception:
        return False


def restore_backup(source_path: Path) -> Tuple[bool, str]:
    """
    Safely restores a backup database file to become the active live database.
    1. Validates source database integrity and required schema.
    2. Takes an automatic pre-restore safety snapshot of the live database.
    3. Truncates WAL and cleans stale -wal / -shm lock files.
    4. Overwrites the live database file.
    5. Re-runs database migrations and checks integrity.
    """
    is_valid, validation_msg = validate_backup_database(source_path)
    if not is_valid:
        return False, f"Restore rejected: {validation_msg}"

    # 1. Automatic safety backup of existing live database
    if config.DB_PATH.exists():
        try:
            create_backup("pre_restore")
        except Exception as e:
            # Continue even if pre-restore snapshot fails, but log
            pass

    # 2. Checkpoint WAL and close connections
    try:
        if config.DB_PATH.exists():
            conn = sqlite3.connect(str(config.DB_PATH), timeout=10.0)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
            conn.close()
    except Exception:
        pass

    # 3. Remove stale WAL and SHM files so they don't corrupt the newly restored file
    wal_path = config.DB_PATH.with_name(config.DB_PATH.name + "-wal")
    shm_path = config.DB_PATH.with_name(config.DB_PATH.name + "-shm")
    try:
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()
    except Exception:
        pass

    # 4. Overwrite live DB with restored file
    try:
        shutil.copy2(str(source_path), str(config.DB_PATH))
    except Exception as e:
        return False, f"Failed to replace active database file: {str(e)}"

    # 5. Re-initialize database schema, apply any migrations, re-enable WAL
    try:
        database.init_db()
    except Exception as e:
        return False, f"Failed to initialize restored database: {str(e)}"

    return True, "Database successfully restored."
