#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# GlycoGuide Remastered — Automatic Raspberry Pi / Linux Installer
# Supports both local cloned setup (./install.sh) and 1-line remote
# install via curl | bash without touching existing patient databases.
# ====================================================================

REPO_URL="https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}====================================================================${NC}"
echo -e "${CYAN}        GlycoGuide Remastered — Raspberry Pi / Linux Installer      ${NC}"
echo -e "${CYAN}====================================================================${NC}"
echo ""

# Resolve actual non-root owner when invoked via sudo
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    TARGET_USER="$SUDO_USER"
else
    TARGET_USER="$(id -un)"
fi
TARGET_GROUP="$(id -gn "$TARGET_USER" 2>/dev/null || echo "$TARGET_USER")"
TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || echo "$HOME")"

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo -e "${RED}[ERROR] Administrator privileges (sudo or root) required to run: $*${NC}"
        exit 1
    fi
}

run_as_target() {
    if [ "$(id -u)" -eq 0 ] && [ "$TARGET_USER" != "root" ]; then
        if command -v sudo >/dev/null 2>&1; then
            sudo -u "$TARGET_USER" -H "$@"
        else
            su -s /bin/bash "$TARGET_USER" -c "$(printf '%q ' "$@")"
        fi
    else
        "$@"
    fi
}

echo -e "[1/5] Checking Python 3, venv, Git, and SQLite dependencies..."
NEED_PACKAGES=0
command -v python3 >/dev/null 2>&1 || NEED_PACKAGES=1
command -v git >/dev/null 2>&1 || NEED_PACKAGES=1
command -v sqlite3 >/dev/null 2>&1 || NEED_PACKAGES=1
command -v curl >/dev/null 2>&1 || NEED_PACKAGES=1
if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
        NEED_PACKAGES=1
    fi
fi

if [ "$NEED_PACKAGES" -eq 1 ]; then
    echo "Installing required system packages..."
    if command -v apt-get >/dev/null 2>&1; then
        run_root apt-get update
        run_root apt-get install -y python3 python3-pip python3-venv git sqlite3 curl ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        run_root dnf install -y python3 python3-pip git sqlite curl ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        run_root pacman -Sy --noconfirm python python-pip git sqlite curl ca-certificates
    else
        echo -e "${RED}[ERROR] Could not detect apt-get, dnf, or pacman. Please install python3, python3-venv, git, sqlite3, and curl manually.${NC}"
        exit 1
    fi
fi

# Determine installation directory (local clone vs curl | bash remote install)
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
APP_DIR=""
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
    CANDIDATE_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
    if [ -f "$CANDIDATE_DIR/app.py" ] && [ -f "$CANDIDATE_DIR/requirements.txt" ]; then
        APP_DIR="$CANDIDATE_DIR"
    fi
fi

if [ -z "$APP_DIR" ] && [ -f "$PWD/app.py" ] && [ -f "$PWD/requirements.txt" ]; then
    APP_DIR="$PWD"
fi

if [ -z "$APP_DIR" ]; then
    if [ -f "$TARGET_HOME/Diabetes-Management-System---Glycoguide-remastered-/app.py" ]; then
        APP_DIR="$TARGET_HOME/Diabetes-Management-System---Glycoguide-remastered-"
    else
        APP_DIR="$TARGET_HOME/glycoguide"
    fi
fi

echo -e "[2/5] Preparing application directory at ${CYAN}$APP_DIR${NC}..."
if [ ! -f "$APP_DIR/app.py" ]; then
    if [ -d "$APP_DIR/.git" ]; then
        run_as_target git -C "$APP_DIR" pull --ff-only
    else
        mkdir -p "$(dirname "$APP_DIR")"
        if [ "$(id -u)" -eq 0 ] && [ "$TARGET_USER" != "root" ]; then
            chown "$TARGET_USER:$TARGET_GROUP" "$(dirname "$APP_DIR")" 2>/dev/null || true
        fi
        run_as_target git clone "$REPO_URL" "$APP_DIR"
    fi
elif [ -d "$APP_DIR/.git" ]; then
    run_as_target git -C "$APP_DIR" config core.fileMode false 2>/dev/null || true
    cur_origin="$(git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
    if [[ "$cur_origin" == *"Diabetes-Management-System-v2"* ]]; then
        echo "Updating git origin remote to GlycoGuide Remastered repository..."
        run_as_target git -C "$APP_DIR" remote set-url origin "$REPO_URL" || true
    fi
fi

run_as_target git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

echo -e "[3/5] Setting up Python virtual environment and packages..."
if [ -d "$APP_DIR/venv" ] && [ ! -x "$APP_DIR/venv/bin/pip" ]; then
    echo "Cleaning incomplete virtual environment..."
    rm -rf "$APP_DIR/venv"
fi

if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

"$APP_DIR/venv/bin/python" -m pip install --upgrade pip -q 2>/dev/null || true
"$APP_DIR/venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
"$APP_DIR/venv/bin/python" -c "import flask, requests; print('Python dependencies verified OK.')"

echo -e "[4/5] Initializing local storage folders (preserving any existing data)..."
mkdir -p "$APP_DIR/data" "$APP_DIR/backups"
chmod +x "$APP_DIR/install.sh" "$APP_DIR/update.sh" "$APP_DIR/backup.sh"

if [ "$(id -u)" -eq 0 ]; then
    chown -R "$TARGET_USER:$TARGET_GROUP" "$APP_DIR"
fi

# Initialize/migrate database schema safely without launching HTTP server yet
run_as_target "$APP_DIR/venv/bin/python" -c "import sys; sys.path.insert(0, '$APP_DIR'); import database; database.init_db()"

echo -e "[5/5] Configuring systemd background service (auto-start on boot)..."
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    SERVICE_FILE="/etc/systemd/system/glycoguide.service"

    run_root tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=GlycoGuide Remastered Type 1 Diabetes Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$TARGET_USER
Group=$TARGET_GROUP
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=GLYCO_PORT=8081
Environment=GLYCO_HOST=0.0.0.0
Environment=GLYCO_NO_BROWSER=1
Environment=GLYCO_MANAGED_BY=systemd

[Install]
WantedBy=multi-user.target
EOF

    run_root systemctl daemon-reload
    run_root systemctl enable glycoguide.service
    run_root systemctl restart glycoguide.service

    # Verify HTTP health before reporting completion
    HEALTH_OK=0
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS http://127.0.0.1:8081/api/auth/status >/dev/null 2>&1; then
            HEALTH_OK=1
            break
        fi
        sleep 1
    done

    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    echo ""
    echo -e "${GREEN}====================================================================${NC}"
    echo -e "${GREEN}       GlycoGuide Remastered Installation Complete!                 ${NC}"
    echo -e "${GREEN}====================================================================${NC}"
    echo ""
    if [ "$HEALTH_OK" -eq 1 ]; then
        echo -e "Service status: ${GREEN}Active, Healthy & Enabled on Boot${NC}"
    else
        echo -e "Service status: ${YELLOW}Started (check: sudo systemctl status glycoguide)${NC}"
    fi
    echo -e "Installed path: ${CYAN}$APP_DIR${NC}"
    echo -e "Local URL:      ${CYAN}http://${LOCAL_IP:-localhost}:8081${NC}"
    echo ""
    if command -v ufw >/dev/null 2>&1 && run_root ufw status 2>/dev/null | grep -q "Status: active"; then
        if ! run_root ufw status 2>/dev/null | grep -q "8081"; then
            echo -e "${YELLOW}[TIP] UFW firewall is active. Allow port 8081 for other devices on Wi-Fi:${NC}"
            echo -e "      ${CYAN}sudo ufw allow 8081/tcp${NC}"
            echo ""
        fi
    fi
    echo -e "Useful Commands:"
    echo -e "  * Live logs:     ${CYAN}sudo journalctl -u glycoguide -f${NC}"
    echo -e "  * Restart app:   ${CYAN}sudo systemctl restart glycoguide${NC}"
    echo -e "  * Update app:    ${CYAN}cd \"$APP_DIR\" && ./update.sh${NC}"
    echo -e "  * Backup DB:     ${CYAN}cd \"$APP_DIR\" && ./backup.sh${NC}"
    echo -e "${GREEN}====================================================================${NC}"
else
    echo ""
    echo -e "${YELLOW}[INFO] systemd was not detected in this environment (container/WSL).${NC}"
    echo -e "Dependencies and database are ready! Launch manually anytime with:"
    echo -e "  ${CYAN}cd \"$APP_DIR\" && ./venv/bin/python3 app.py${NC}"
fi
