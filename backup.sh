#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# GlycoGuide Remastered — Safe WAL-Aware SQLite Backup Script
# ====================================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_FILE="$APP_DIR/data/glycoguide.db"
BACKUP_DIR="$APP_DIR/backups"

mkdir -p "$BACKUP_DIR"

if [ -f "$DATA_FILE" ]; then
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/glycoguide_backup_$TIMESTAMP.db"

    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DATA_FILE" ".backup '$BACKUP_FILE'"
    elif [ -x "$APP_DIR/venv/bin/python" ]; then
        "$APP_DIR/venv/bin/python" -c "import sqlite3; s=sqlite3.connect('$DATA_FILE'); d=sqlite3.connect('$BACKUP_FILE'); s.backup(d); d.close(); s.close()"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import sqlite3; s=sqlite3.connect('$DATA_FILE'); d=sqlite3.connect('$BACKUP_FILE'); s.backup(d); d.close(); s.close()"
    else
        cp "$DATA_FILE" "$BACKUP_FILE"
    fi

    echo "Backup created successfully: $BACKUP_FILE"

    # Retain backups for 30 days
    find "$BACKUP_DIR" -type f -name "glycoguide_backup_*.db" -mtime +30 -delete 2>/dev/null || true
else
    echo "Database file $DATA_FILE does not exist yet."
fi
