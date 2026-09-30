#!/usr/bin/env bash
# Lokamania 09 — daily backup of the application workbook.
#
# Installed to /usr/local/sbin/lokamania-backup by deploy/setup.sh and run
# from cron once a day. Keeps KEEP_DAYS days of history (default 30).
set -euo pipefail

DATA_DIR=/srv/lokamania-data
BACKUP_DIR="$DATA_DIR/backups"
WORKBOOK="$DATA_DIR/Lokamania_09_Brand_Applications_FINAL.xlsx"
KEEP_DAYS="${KEEP_DAYS:-30}"

log() { printf '%s  %s\n' "$(date -Is)" "$*"; }

if [ ! -f "$WORKBOOK" ]; then
  log "ERROR: workbook missing at $WORKBOOK — nothing backed up."
  exit 1
fi

mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y%m%d_%H%M%S)
NAME="$(basename "${WORKBOOK%.xlsx}")_backup_${STAMP}.xlsx"
DEST="$BACKUP_DIR/$NAME"

# Copy to a hidden temp file first, then move into place, so a partially
# written file is never visible under the real backup name.
TMP="$(mktemp "$BACKUP_DIR/.partial_XXXXXX.xlsx")"
trap 'rm -f "$TMP"' EXIT
cp -p "$WORKBOOK" "$TMP"
mv "$TMP" "$DEST"
trap - EXIT

# Prune history.
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*_backup_*.xlsx' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true

COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*_backup_*.xlsx' | wc -l | tr -d ' ')
log "backup written: $NAME  (${COUNT} kept, ${KEEP_DAYS}-day limit)"
