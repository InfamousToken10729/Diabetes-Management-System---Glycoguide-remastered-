import sqlite3
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
import config

def get_db():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Profiles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                device_id TEXT PRIMARY KEY,
                username TEXT,
                glucose_unit TEXT NOT NULL DEFAULT 'mg/dL',
                birth_date TEXT,
                age INTEGER,
                weight_kg REAL,
                height_cm REAL,
                gender TEXT,
                target_low INTEGER NOT NULL DEFAULT 70,
                target_high INTEGER NOT NULL DEFAULT 180,
                target_bg INTEGER NOT NULL DEFAULT 110,
                icr REAL,
                isf REAL,
                insulin_type TEXT NOT NULL DEFAULT 'NovoRapid',
                insulin_duration_hours REAL NOT NULL DEFAULT 4.0,
                ai_api_key TEXT,
                ai_model TEXT,
                ai_base_url TEXT,
                github_repo TEXT,
                theme TEXT NOT NULL DEFAULT 'dark',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Migration: Ensure birth_date exists if table was already created
        cursor.execute("PRAGMA table_info(profiles);")
        p_cols = [r["name"] for r in cursor.fetchall()]
        if "birth_date" not in p_cols:
            cursor.execute("ALTER TABLE profiles ADD COLUMN birth_date TEXT;")

        # 2. Device Users (Master account & password)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_users (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                avatar_color TEXT NOT NULL DEFAULT 'cyan',
                is_main INTEGER NOT NULL DEFAULT 1,
                password_hash TEXT,
                password_salt TEXT,
                recovery_key_hash TEXT,
                recovery_key_salt TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Migration: Ensure recovery key columns exist if table was already created
        cursor.execute("PRAGMA table_info(device_users);")
        u_cols = [r["name"] for r in cursor.fetchall()]
        if "recovery_key_hash" not in u_cols:
            cursor.execute("ALTER TABLE device_users ADD COLUMN recovery_key_hash TEXT;")
        if "recovery_key_salt" not in u_cols:
            cursor.execute("ALTER TABLE device_users ADD COLUMN recovery_key_salt TEXT;")

        # 3. Log Entries (Glucose, Insulin, Meals, Tags)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                bg_value INTEGER,
                ketone_level TEXT,
                insulin_units REAL,
                meal_relation TEXT,
                meal_offset_value INTEGER,
                meal_offset_unit TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                carbs REAL,
                protein REAL,
                fat REAL,
                sugar REAL,
                meal_description TEXT,
                dose_kind TEXT,
                notes TEXT,
                spoiled_insulin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_log_occurred ON log_entries (occurred_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_log_device ON log_entries (device_id);")

        # 4. Reminders (Post-meal BG checks, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                due_at TEXT NOT NULL,
                title TEXT NOT NULL,
                units REAL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        # 5. Sessions (Inactivity tracking & device auth)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_active_at INTEGER NOT NULL
            );
        """)

        # 6. System & Security Audit Logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                device_id TEXT NOT NULL DEFAULT 'family-shared-device'
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_occurred ON audit_logs (occurred_at DESC);")

        # Seed default profile if none exists
        cursor.execute("SELECT device_id FROM profiles LIMIT 1;")
        if not cursor.fetchone():
            now_str = datetime.now(timezone.utc).isoformat()
            default_device = "family-shared-device"
            cursor.execute("""
                INSERT INTO profiles (
                    device_id, username, glucose_unit, target_low, target_high, target_bg,
                    icr, isf, insulin_type, insulin_duration_hours,
                    ai_model, ai_base_url, github_repo, theme, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                default_device, "Main User", "mg/dL", 70, 180, 110,
                None, None, "NovoRapid", 4.0,
                "gemini-2.5-flash", "https://generativelanguage.googleapis.com",
                "https://github.com/InfamousToken10729/Diabetes-Management-System-v2",
                "dark", now_str, now_str
            ))
            cursor.execute("""
                INSERT INTO device_users (
                    id, device_id, display_name, avatar_color, is_main,
                    password_hash, password_salt, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, 1, NULL, NULL, ?, ?
                )
            """, (
                "usr_default_main", default_device, "Main Account", "cyan", now_str, now_str
            ))

        conn.commit()

# Profile methods
def get_profile(device_id: str = "family-shared-device") -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profiles WHERE device_id = ? LIMIT 1;", (device_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM profiles LIMIT 1;")
            row = cursor.fetchone()
        return dict(row) if row else None

def calculate_age_from_dob(dob_str: Optional[str]) -> Optional[int]:
    if not dob_str:
        return None
    try:
        from datetime import date
        dob = date.fromisoformat(dob_str.strip()[:10])
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return None

def update_profile(device_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        
        # If birth_date is provided, auto-calculate age
        if data.get("birth_date"):
            computed_age = calculate_age_from_dob(data["birth_date"])
            if computed_age is not None:
                data["age"] = computed_age

        allowed_fields = [
            "username", "glucose_unit", "birth_date", "age", "weight_kg", "height_cm", "gender",
            "target_low", "target_high", "target_bg", "icr", "isf",
            "insulin_type", "insulin_duration_hours", "ai_api_key", "ai_model",
            "ai_base_url", "github_repo", "theme"
        ]
        
        updates = []
        params = []
        for key in allowed_fields:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
        
        updates.append("updated_at = ?")
        params.append(now_str)
        params.append(device_id)
        
        cursor.execute(f"UPDATE profiles SET {', '.join(updates)} WHERE device_id = ?;", params)
        conn.commit()
        return get_profile(device_id) or {}

# User & Master Account methods
def get_main_user() -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM device_users WHERE is_main = 1 LIMIT 1;")
        row = cursor.fetchone()
        return dict(row) if row else None

def update_main_user_password(hash_val: Optional[str], salt_val: Optional[str]):
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            UPDATE device_users 
            SET password_hash = ?, password_salt = ?, updated_at = ? 
            WHERE is_main = 1;
        """, (hash_val, salt_val, now_str))
        conn.commit()

def update_main_user_credentials(
    password_hash: Optional[str] = None,
    password_salt: Optional[str] = None,
    recovery_key_hash: Optional[str] = None,
    recovery_key_salt: Optional[str] = None,
    display_name: Optional[str] = None
):
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        updates = ["updated_at = ?"]
        params = [now_str]
        
        if password_hash is not None:
            updates.append("password_hash = ?")
            params.append(password_hash)
        if password_salt is not None:
            updates.append("password_salt = ?")
            params.append(password_salt)
        if recovery_key_hash is not None:
            updates.append("recovery_key_hash = ?")
            params.append(recovery_key_hash)
        if recovery_key_salt is not None:
            updates.append("recovery_key_salt = ?")
            params.append(recovery_key_salt)
        if display_name is not None and display_name.strip():
            updates.append("display_name = ?")
            params.append(display_name.strip())
            
        cursor.execute(f"""
            UPDATE device_users 
            SET {', '.join(updates)} 
            WHERE is_main = 1;
        """, params)
        conn.commit()

def reset_main_account(
    display_name: str = "Main Account",
    password_hash: Optional[str] = None,
    password_salt: Optional[str] = None,
    recovery_key_hash: Optional[str] = None,
    recovery_key_salt: Optional[str] = None
):
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        # Reset main user
        cursor.execute("""
            UPDATE device_users 
            SET display_name = ?,
                password_hash = ?,
                password_salt = ?,
                recovery_key_hash = ?,
                recovery_key_salt = ?,
                updated_at = ?
            WHERE is_main = 1;
        """, (display_name, password_hash, password_salt, recovery_key_hash, recovery_key_salt, now_str))
        # Clear old sessions so new credentials take effect cleanly
        cursor.execute("DELETE FROM sessions;")
        conn.commit()

# Log Entries methods
def add_log_entry(data: Dict[str, Any]) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        occurred_at = data.get("occurred_at") or now_str
        
        tags_json = json.dumps(data.get("tags") or [])
        
        cursor.execute("""
            INSERT INTO log_entries (
                device_id, occurred_at, bg_value, ketone_level, insulin_units,
                meal_relation, meal_offset_value, meal_offset_unit, tags,
                carbs, protein, fat, sugar, meal_description, dose_kind,
                notes, spoiled_insulin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            data.get("device_id", "family-shared-device"),
            occurred_at,
            data.get("bg_value"),
            data.get("ketone_level"),
            data.get("insulin_units"),
            data.get("meal_relation"),
            data.get("meal_offset_value"),
            data.get("meal_offset_unit"),
            tags_json,
            data.get("carbs"),
            data.get("protein"),
            data.get("fat"),
            data.get("sugar"),
            data.get("meal_description"),
            data.get("dose_kind"),
            data.get("notes"),
            1 if data.get("spoiled_insulin") else 0,
            now_str
        ))
        conn.commit()
        return cursor.lastrowid

def get_log_entries(
    device_id: str = "family-shared-device",
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = 200
) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM log_entries WHERE device_id = ?"
        params: List[Any] = [device_id]
        
        if days:
            cutoff = datetime.fromtimestamp(time.time() - (days * 86400), timezone.utc).isoformat()
            query += " AND occurred_at >= ?"
            params.append(cutoff)
        elif start_date and end_date:
            query += " AND occurred_at >= ? AND occurred_at <= ?"
            params.append(start_date)
            params.append(end_date)
            
        query += " ORDER BY occurred_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
            
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
            except Exception:
                d["tags"] = []
            result.append(d)
        return result

def get_log_entry(entry_id: int, device_id: str = "family-shared-device") -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM log_entries WHERE id = ? AND device_id = ? LIMIT 1;", (entry_id, device_id))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        except Exception:
            d["tags"] = []
        return d

def update_log_entry(entry_id: int, data: Dict[str, Any], device_id: str = "family-shared-device") -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        fields = [
            "occurred_at", "bg_value", "ketone_level", "insulin_units", "meal_relation",
            "meal_offset_value", "meal_offset_unit", "tags", "carbs", "protein",
            "fat", "sugar", "meal_description", "dose_kind", "notes", "spoiled_insulin"
        ]
        updates = []
        params = []
        for f in fields:
            if f in data:
                if f == "tags":
                    updates.append("tags = ?")
                    params.append(json.dumps(data["tags"] or []))
                elif f == "spoiled_insulin":
                    updates.append("spoiled_insulin = ?")
                    params.append(1 if data["spoiled_insulin"] else 0)
                else:
                    updates.append(f"{f} = ?")
                    params.append(data[f])
        
        if not updates:
            return False
            
        params.extend([entry_id, device_id])
        cursor.execute(f"UPDATE log_entries SET {', '.join(updates)} WHERE id = ? AND device_id = ?;", params)
        conn.commit()
        return cursor.rowcount > 0

def delete_log_entry(entry_id: int, device_id: str = "family-shared-device") -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM log_entries WHERE id = ? AND device_id = ?;", (entry_id, device_id))
        conn.commit()
        return cursor.rowcount > 0

def toggle_spoiled_insulin(entry_id: int, spoiled: bool, device_id: str = "family-shared-device") -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE log_entries SET spoiled_insulin = ? WHERE id = ? AND device_id = ?;", (1 if spoiled else 0, entry_id, device_id))
        conn.commit()
        return cursor.rowcount > 0

# Reminders
def add_reminder(device_id: str, due_at: str, title: str, units: Optional[float] = None) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO reminders (device_id, due_at, title, units, done, created_at)
            VALUES (?, ?, ?, ?, 0, ?);
        """, (device_id, due_at, title, units, now_str))
        conn.commit()
        return cursor.lastrowid

def get_reminders(device_id: str = "family-shared-device", include_done: bool = False) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM reminders WHERE device_id = ?"
        params: List[Any] = [device_id]
        if not include_done:
            query += " AND done = 0"
        query += " ORDER BY due_at ASC;"
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

def mark_reminder_done(reminder_id: int, device_id: str = "family-shared-device") -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE reminders SET done = 1 WHERE id = ? AND device_id = ?;", (reminder_id, device_id))
        conn.commit()
        return cursor.rowcount > 0

# Session Management
def create_session(session_id: str, device_id: str):
    now = int(time.time())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (session_id, device_id, created_at, last_active_at)
            VALUES (?, ?, ?, ?);
        """, (session_id, device_id, now, now))
        conn.commit()

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ? LIMIT 1;", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def touch_session(session_id: str):
    now = int(time.time())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET last_active_at = ? WHERE session_id = ?;", (now, session_id))
        conn.commit()

def delete_session(session_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ?;", (session_id,))
        conn.commit()

# Clear Data
def clear_all_clinical_data(device_id: str = "family-shared-device"):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM log_entries WHERE device_id = ?;", (device_id,))
        cursor.execute("DELETE FROM reminders WHERE device_id = ?;", (device_id,))
        conn.commit()

def factory_reset_all_data_and_accounts(device_id: str = "family-shared-device"):
    """
    Completely wipes the master account, password, credentials, clinical logs,
    reminders, and sessions, resetting the device to initial unconfigured factory state.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("DELETE FROM log_entries WHERE device_id = ?;", (device_id,))
        cursor.execute("DELETE FROM reminders WHERE device_id = ?;", (device_id,))
        cursor.execute("DELETE FROM sessions WHERE device_id = ?;", (device_id,))
        cursor.execute("""
            UPDATE device_users 
            SET display_name = 'Main Account',
                password_hash = NULL,
                password_salt = NULL,
                recovery_key_hash = NULL,
                recovery_key_salt = NULL,
                updated_at = ?
            WHERE device_id = ?;
        """, (now_str, device_id))
        cursor.execute("""
            UPDATE profiles 
            SET username = 'Main Account',
                glucose_unit = 'mg/dL',
                target_bg = 110,
                target_low = 70,
                target_high = 180,
                icr = NULL,
                isf = NULL,
                insulin_type = 'NovoRapid',
                insulin_duration_hours = 4.0,
                theme = 'obsidian',
                updated_at = ?
            WHERE device_id = ?;
        """, (now_str, device_id))
        conn.commit()

# Audit Logging
def add_audit_log(event_type: str, description: str, device_id: str = "family-shared-device"):
    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO audit_logs (occurred_at, event_type, description, device_id)
            VALUES (?, ?, ?, ?);
        """, (now_str, event_type, description, device_id))
        conn.commit()

def get_audit_logs(limit: int = 100) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY occurred_at DESC LIMIT ?;", (limit,))
        return [dict(r) for r in cursor.fetchall()]
