#!/usr/bin/env bash
set -e

# ====================================================================
# GlycoGuide Remastered — 1-Command Raspberry Pi / Linux Installer
# ====================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}====================================================================${NC}"
echo -e "${CYAN}        GlycoGuide Remastered — Raspberry Pi Installer              ${NC}"
echo -e "${CYAN}====================================================================${NC}"
echo ""

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(id -un)"

echo -e "[1/4] Checking Python 3 and system dependencies..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] Python 3 is not installed. Installing...${NC}"
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv
fi

echo -e "[2/4] Setting up Python virtual environment..."
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo -e "[3/4] Creating local database directory..."
mkdir -p "$APP_DIR/data"
mkdir -p "$APP_DIR/backups"

echo -e "[4/4] Installing systemd service (auto-start on boot)..."
SERVICE_FILE="/etc/systemd/system/glycoguide.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=GlycoGuide Remastered Type 1 Diabetes Assistant
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=5
Environment=GLYCO_PORT=8081
Environment=GLYCO_HOST=0.0.0.0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable glycoguide.service
sudo systemctl restart glycoguide.service

# Detect Local IP Address
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}====================================================================${NC}"
echo -e "${GREEN}       GlycoGuide Remastered Installation Complete!                 ${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo ""
echo -e "Service status: ${GREEN}Active & Enabled on Boot${NC}"
echo -e "Access the app locally from any device on your Wi-Fi:"
echo -e "  -> ${CYAN}http://${LOCAL_IP:-localhost}:8081${NC}"
echo ""
echo -e "DuckDNS / Remote Access Setup:"
echo -e "  1. Forward external port 8081 to internal port 8081 of this Raspberry Pi."
echo -e "  2. Access anywhere via: http://your-domain.duckdns.org:8081"
echo ""
echo -e "To view live logs:    ${CYAN}sudo journalctl -u glycoguide -f${NC}"
echo -e "To restart service:   ${CYAN}sudo systemctl restart glycoguide${NC}"
echo -e "${GREEN}====================================================================${NC}"
