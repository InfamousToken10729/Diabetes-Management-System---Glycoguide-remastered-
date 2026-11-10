import os
import sys
import secrets
from pathlib import Path

# Base Paths (supports both standard python and PyInstaller --onefile)
if getattr(sys, 'frozen', False):
    # Running as compiled .exe
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = DATA_DIR / "glycoguide.db"

# Server Settings
HOST = os.environ.get("GLYCO_HOST", "0.0.0.0")
PORT = int(os.environ.get("GLYCO_PORT", 8081))
DEBUG = os.environ.get("GLYCO_DEBUG", "false").lower() in ("1", "true", "yes")

# Secret key for sessions (persisted to file if not provided via env)
SECRET_FILE = DATA_DIR / ".session_secret"
if "SECRET_KEY" in os.environ:
    SECRET_KEY = os.environ["SECRET_KEY"]
else:
    if SECRET_FILE.exists():
        SECRET_KEY = SECRET_FILE.read_text(encoding="utf-8").strip()
    else:
        SECRET_KEY = secrets.token_hex(32)
        try:
            SECRET_FILE.write_text(SECRET_KEY, encoding="utf-8")
        except Exception:
            pass

# Security & Sessions
SESSION_COOKIE_NAME = "glyco_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
INACTIVITY_TIMEOUT_SECONDS = 15 * 60  # 15 minutes of inactivity

# Clinical Defaults
DEFAULT_GLUCOSE_UNIT = "mg/dL"  # "mg/dL" or "mmol/L"
DEFAULT_TARGET_LOW = 70
DEFAULT_TARGET_HIGH = 180
DEFAULT_TARGET_BG = 110
DEFAULT_INSULIN_TYPE = "NovoRapid"
DEFAULT_INSULIN_DURATION = 4.0  # DIA in hours

# Repository & Self-Update Defaults
DEFAULT_GITHUB_REPO = "https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-"
LEGACY_GITHUB_REPOS = {
    "https://github.com/InfamousToken10729/Diabetes-Management-System-v2",
    "https://github.com/InfamousToken10729/Diabetes-Management-System-v2.git",
}
