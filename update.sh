#!/usr/bin/env bash
set -e

# ====================================================================
# GlycoGuide Remastered — 1-Click Update Script
# ====================================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "Checking for updates from Git repository..."
git pull

echo "Updating Python packages..."
if [ -d "$APP_DIR/venv" ]; then
    "$APP_DIR/venv/bin/pip" install -q -r requirements.txt
else
    pip install -q -r requirements.txt
fi

if systemctl is-active --quiet glycoguide.service 2>/dev/null; then
    echo "Restarting GlycoGuide service..."
    sudo systemctl restart glycoguide.service
fi

echo "Update complete! Your local database was safely preserved."
