#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# GlycoGuide Remastered — Safe 1-Command Update Script
# ====================================================================

REPO_URL="https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "[1/4] Creating automatic database safety backup..."
bash "$APP_DIR/backup.sh" || true

echo "[2/4] Pulling latest code from GitHub..."
git -c "safe.directory=$APP_DIR" config core.fileMode false 2>/dev/null || true
cur_origin="$(git -c "safe.directory=$APP_DIR" remote get-url origin 2>/dev/null || true)"
if [[ "$cur_origin" == *"Diabetes-Management-System-v2"* ]]; then
    git -c "safe.directory=$APP_DIR" remote set-url origin "$REPO_URL" || true
fi

git -c "safe.directory=$APP_DIR" pull --ff-only

echo "[3/4] Updating Python dependencies..."
if [ -x "$APP_DIR/venv/bin/python" ]; then
    "$APP_DIR/venv/bin/python" -m pip install -q -r requirements.txt
else
    python3 -m pip install -q -r requirements.txt
fi

chmod +x "$APP_DIR/install.sh" "$APP_DIR/update.sh" "$APP_DIR/backup.sh"

echo "[4/4] Restarting service if installed..."
if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled --quiet glycoguide.service 2>/dev/null; then
    sudo systemctl restart glycoguide.service
    echo "GlycoGuide service restarted."
fi

echo "Update complete! Your local database was safely preserved."
