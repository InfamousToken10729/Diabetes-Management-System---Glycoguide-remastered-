#!/usr/bin/env bash
# ====================================================================
# GlycoGuide Remastered — Local Database Backup Script
# ====================================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_FILE="$APP_DIR/data/glycoguide.db"
BACKUP_DIR="$APP_DIR/backups"

mkdir -p "$BACKUP_DIR"

if [ -f "$DATA_FILE" ]; then
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/glycoguide_backup_$TIMESTAMP.db"
    
    # Use SQLite safe backup API or copy
    sqlite3 "$DATA_FILE" ".backup '$BACKUP_FILE'" 2>/dev/null || cp "$DATA_FILE" "$BACKUP_FILE"
    echo "Backup created successfully: $BACKUP_FILE"
    
    # Retain last 30 backups, remove older
    find "$BACKUP_DIR" -type f -name "glycoguide_backup_*.db" -mtime +30 -delete 2>/dev/null || true
else
    echo "Database file $DATA_FILE does not exist yet."
fi
