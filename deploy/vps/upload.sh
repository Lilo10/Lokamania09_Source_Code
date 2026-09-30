#!/usr/bin/env bash
# Lokamania 09 — upload the site to your server and go live.
#
# Run this from your Mac, from the project folder:
#
#     ./deploy/upload.sh                    # full upload + first-time setup
#     ./deploy/upload.sh --code-only        # just push code changes
#     ./deploy/upload.sh --no-setup         # upload without running setup.sh
#
# The first time, the target should be root@your-server-ip.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/lokamania
DATA_DIR=/srv/lokamania-data
WORKBOOK_NAME=Lokamania_09_Brand_Applications_FINAL.xlsx

FULL_SETUP=1
UPLOAD_WORKBOOK=1
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --code-only)   UPLOAD_WORKBOOK=0; FULL_SETUP=0 ;;
    --no-setup)    FULL_SETUP=0 ;;
    --help|-h)     sed -n '2,10p' "$0"; exit 0 ;;
    *)             TARGET="$arg" ;;
  esac
done
TARGET="${TARGET:-root@mylokamania.com}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Read a KEY=value out of a .env file, stripping any surrounding quotes.
envval() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -1 | tr -d '\042\047'; }

printf '\n\033[1mLokamania 09 - deploy\033[0m\n'
printf 'project : %s\n' "$PROJECT_DIR"
printf 'server  : %s\n'    "$TARGET"

# --------------------------------------------------------------- local checks
step "1/4  Checking this machine"
command -v rsync >/dev/null 2>&1 || die "rsync is not installed. Run:  brew install rsync"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" true 2>/dev/null \
  || die "Cannot log in to $TARGET without a password prompt. Test with:  ssh $TARGET"

# --------------------------------------------------- what is the workbook here
LOCAL_ENV="$PROJECT_DIR/.env"
LOCAL_WORKBOOK=""
[ -f "$LOCAL_ENV" ] && LOCAL_WORKBOOK="$(envval EXCEL_PATH "$LOCAL_ENV")"
if [ -z "$LOCAL_WORKBOOK" ] || [ ! -f "$LOCAL_WORKBOOK" ]; then
  LOCAL_WORKBOOK="$(find "$HOME/Library/CloudStorage" "$HOME/Documents" "$HOME/Desktop" \
                     -name "$WORKBOOK_NAME" -type f 2>/dev/null | head -1)"
fi

# ------------------------------------------------------------- server prep
step "2/4  Preparing the server"
ssh "$TARGET" 'DEBIAN_FRONTEND=noninteractive apt-get update -qq &&
               DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync curl ca-certificates &&
               mkdir -p /opt/lokamania /srv/lokamania-data/backups'
echo "    server ready."

# ----------------------------------------------------------------- code push
step "3/4  Uploading the website"
rsync -az --delete --human-readable --stats \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'deploy/upload.sh' \
  --exclude '*.xlsx' \
  "$PROJECT_DIR/" "$TARGET:$APP_DIR/"

# ------------------------------------------------------------------- data
if [ "$UPLOAD_WORKBOOK" -eq 1 ]; then
  [ -n "$LOCAL_WORKBOOK" ] || die "Could not find $WORKBOOK_NAME on this Mac"
  echo "    workbook: $LOCAL_WORKBOOK"
  rsync -az --human-readable --stats "$LOCAL_WORKBOOK" "$TARGET:$DATA_DIR/$WORKBOOK_NAME"
else
  echo "    Skipping workbook upload; the server keeps its own copy."
fi

# ------------------------------------------------------------------- setup
if [ "$FULL_SETUP" -eq 1 ]; then
  step "4/4  Running setup.sh on the server (installs Caddy, gunicorn, firewall)"
  PW=""
  if [ -f "$LOCAL_ENV" ]; then
    PW="$(envval ADMIN_PASSWORD "$LOCAL_ENV")"
    [ -n "$PW" ] && echo "    Reusing your existing admin password."
  fi
  ssh "$TARGET" "APP_USER=lokamania DEPLOY_DIR=$APP_DIR/deploy ADMIN_PASSWORD='$PW' bash -s" \
    < "$PROJECT_DIR/deploy/setup.sh"
else
  echo
  echo "    Skipping setup.sh. To (re)install the server software run:"
  echo "        ssh $TARGET \"DEPLOY_DIR=$APP_DIR/deploy bash -s\" < $PROJECT_DIR/deploy/setup.sh"
fi

# ------------------------------------------------------------------- verify
step "Health check"
if ssh "$TARGET" 'curl -fsS --max-time 10 http://127.0.0.1:8000/api/health'; then
  printf '\n\033[1;32m==> The app is running on the server.\033[0m\n\n'
else
  printf '\n\033[1;33m==> Uploaded, but the app is not answering yet.\033[0m\n'
  echo "    Look at the log:  ssh $TARGET 'journalctl -u lokamania -n 40 --no-pager'"
fi
cat <<'EOF'

Next:  add a DNS "A" record for your domain pointing at this server's
       public IPv4 address, then wait a few minutes and open your site.
EOF
