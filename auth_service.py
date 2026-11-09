import os
import time
import hashlib
import secrets
from typing import Optional, Dict, Any, Tuple
import config
import database

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return dk.hex(), salt

def verify_password(password: str, hashed: str, salt: str) -> bool:
    dk, _ = hash_password(password, salt)
    return secrets.compare_digest(dk, hashed)

def normalize_recovery_key(key: str) -> str:
    """Normalizes recovery key: trims whitespace and ignores casing for high resilience."""
    return key.strip().lower()

def hash_recovery_key(key: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    norm = normalize_recovery_key(key)
    dk = hashlib.pbkdf2_hmac("sha256", norm.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return dk.hex(), salt

def verify_recovery_key(key: str, hashed: str, salt: str) -> bool:
    norm = normalize_recovery_key(key)
    dk, _ = hash_recovery_key(norm, salt)
    return secrets.compare_digest(dk, hashed)

def is_password_configured() -> bool:
    main_user = database.get_main_user()
    return bool(main_user and main_user.get("password_hash"))

def authenticate_master_password(password: str) -> bool:
    main_user = database.get_main_user()
    if not main_user or not main_user.get("password_hash") or not main_user.get("password_salt"):
        return False
    return verify_password(password, main_user["password_hash"], main_user["password_salt"])

def authenticate_recovery_key(key: str) -> bool:
    main_user = database.get_main_user()
    if not main_user or not main_user.get("recovery_key_hash") or not main_user.get("recovery_key_salt"):
        return False
    return verify_recovery_key(key, main_user["recovery_key_hash"], main_user["recovery_key_salt"])

def set_master_password(new_password: str) -> bool:
    if not new_password or len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    h, s = hash_password(new_password)
    database.update_main_user_password(h, s)
    return True

def set_master_credentials(new_password: str, recovery_key: Optional[str] = None, display_name: Optional[str] = None) -> bool:
    if not new_password or len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    p_hash, p_salt = hash_password(new_password)
    
    r_hash, r_salt = None, None
    if recovery_key and recovery_key.strip():
        r_hash, r_salt = hash_recovery_key(recovery_key)
        
    database.update_main_user_credentials(
        password_hash=p_hash,
        password_salt=p_salt,
        recovery_key_hash=r_hash,
        recovery_key_salt=r_salt,
        display_name=display_name
    )
    return True

def reset_password_with_recovery_key(recovery_key: str, new_password: str) -> bool:
    if not authenticate_recovery_key(recovery_key):
        return False
    return set_master_password(new_password)

def emergency_reset_credentials(new_password: str, recovery_key: Optional[str] = None) -> bool:
    return set_master_credentials(new_password, recovery_key)

def create_or_reset_account(
    display_name: str,
    password: str,
    recovery_key: Optional[str] = None,
    glucose_unit: str = "mg/dL",
    wipe_data: bool = True
) -> str:
    name = (display_name or "Main Account").strip()
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    
    p_hash, p_salt = hash_password(password)
    r_hash, r_salt = None, None
    if recovery_key and recovery_key.strip():
        r_hash, r_salt = hash_recovery_key(recovery_key)

    # Reset main user credentials and clear old sessions
    database.reset_main_account(
        display_name=name,
        password_hash=p_hash,
        password_salt=p_salt,
        recovery_key_hash=r_hash,
        recovery_key_salt=r_salt
    )

    # Update profile display name & glucose unit
    database.update_profile("family-shared-device", {
        "username": name,
        "glucose_unit": glucose_unit
    })

    # Wipe existing logs if requested
    if wipe_data:
        database.clear_all_clinical_data()

    # Create new fresh authenticated session
    return create_device_session("family-shared-device")

def create_device_session(device_id: str = "family-shared-device") -> str:
    session_id = secrets.token_urlsafe(32)
    database.create_session(session_id, device_id)
    return session_id

def validate_session(session_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validates the session ID against database and enforces the 15-minute inactivity timeout.
    Returns (is_valid, reason_if_invalid).
    """
    # If no master password has been configured yet, access is open for initial setup
    if not is_password_configured():
        return True, None

    if not session_id:
        return False, "NO_SESSION"

    sess = database.get_session(session_id)
    if not sess:
        return False, "INVALID_SESSION"

    now = int(time.time())
    last_active = sess.get("last_active_at", 0)
    
    if (now - last_active) > config.INACTIVITY_TIMEOUT_SECONDS:
        database.delete_session(session_id)
        return False, "SESSION_EXPIRED"

    # Refresh session activity
    database.touch_session(session_id)
    return True, None
