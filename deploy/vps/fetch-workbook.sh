#!/usr/bin/env bash
# Lokamania 09 — download the live workbook from your server to this Mac.
#
# The SERVER holds the master copy once the site is live. Run this to get a
# fresh copy to read in Excel. Never edit and re-upload the workbook — the
# server is the only thing allowed to write to it.
#
#     ./deploy/fetch-workbook.sh
#
# Saves to: ~/Desktop/Lokamania_09_Brand_Applications_LIVE_<date-time>.xlsx
set -euo pipefail

TARGET="${1:-root@mylokamania.com}"
DATA_DIR=/srv/lokamania-data
WORKBOOK=Lokamania_09_Brand_Applications_FINAL.xlsx
DEST="$HOME/Desktop/${WORKBOOK%.xlsx}_LIVE_$(date +%Y%m%d_%H%M%S).xlsx"

printf 'Downloading the live workbook from %s ...\n' "$TARGET"
ssh "$TARGET" "sudo cat '$DATA_DIR/$WORKBOOK'" > "$DEST" || {
  printf '\n\033[1;31mDownload failed.\033[0m\n' >&2
  rm -f "$DEST"
  exit 1
}

SIZE=$(du -h "$DEST" | cut -f1)
printf '\n\033[1;32mSaved:\033[0m %s  (%s)\n\n' "$DEST" "$SIZE"
cat <<'EOF'
Open it read-only to have a look. If you save any change in Excel it will
NOT reach the server — and it can hide new submissions if you leave it open
while someone applies. Close it when you are done.
EOF
