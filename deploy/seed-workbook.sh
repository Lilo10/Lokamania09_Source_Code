#!/usr/bin/env bash
# Lokamania 09 — copy the workbook from this Mac onto the Railway volume.
#
# Run this ONCE, after the service is deployed and a volume is attached:
#
#     ./deploy/seed-workbook.sh
#
# It uploads the real workbook to /data inside the container, which is where
# the server looks for it. Running it again would OVERWRITE the live workbook,
# so it refuses unless you pass --force.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="$PROJECT_DIR/.env"
WORKBOOK_NAME=Lokamania_09_Brand_Applications_FINAL.xlsx
REMOTE_DIR="/data"
REMOTE_PATH="$REMOTE_DIR/$WORKBOOK_NAME"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------- find the workbook
envval() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -1 | tr -d '\042\047'; }
LOCAL_WORKBOOK=""
[ -f "$LOCAL_ENV" ] && LOCAL_WORKBOOK="$(envval EXCEL_PATH "$LOCAL_ENV")"
if [ -z "$LOCAL_WORKBOOK" ] || [ ! -f "$LOCAL_WORKBOOK" ]; then
  LOCAL_WORKBOOK="$(find "$HOME/Library/CloudStorage" "$HOME/Documents" "$HOME/Desktop" \
                     -name "$WORKBOOK_NAME" -type f 2>/dev/null | head -1)"
fi
[ -n "$LOCAL_WORKBOOK" ] || die "Could not find $WORKBOOK_NAME on this Mac"
[ "$FORCE" -eq 1 ] || die "Refusing to overwrite a live workbook. If you are sure, run:  $0 --force"

# ------------------------------------------------------------- prerequisites
step "1/4  Checking the Railway CLI"
command -v railway >/dev/null 2>&1 || die "Railway CLI not installed.
  Install it with:   npm install -g @railway/cli
  (or download it from  https://railway.com/cli )"
railway --version

step "2/4  Checking you are logged in"
railway whoami >/dev/null 2>&1 || die "Not logged in. Run:  railway login"

step "3/4  Working out the service address"
SERVICE="${RAILWAY_SSH_HOST:-}"
if [ -z "$SERVICE" ]; then
  printf '  Enter the service domain shown in the Railway dashboard\n'
  printf '  (Settings -> Networking -> Domain, e.g. mylokamania.up.railway.app): '
  read -r SERVICE
fi
[ -n "$SERVICE" ] || die "No service domain given"
printf '  service: %s\n' "$SERVICE"

# ------------------------------------------------------------------- upload
step "4/4  Uploading the workbook to $REMOTE_PATH"
echo "  from: $LOCAL_WORKBOOK"
echo "  size: $(du -h "$LOCAL_WORKBOOK" | cut -f1)"

# Make sure an SSH key is registered, otherwise the transfer is refused.
railway ssh keys list >/dev/null 2>&1 || railway login >/dev/null 2>&1 || true
if ! railway ssh keys list 2>/dev/null | grep -q .; then
  echo "  no SSH key registered yet — adding your default one"
  railway ssh keys add --name "$(whoami)-laptop" || die "Could not add an SSH key. Run:  railway ssh keys add"
fi

scp "$LOCAL_WORKBOOK" "${SERVICE}@ssh.railway.com:${REMOTE_PATH}" \
  || die "Upload failed. Check that the service is running and the volume is attached at $REMOTE_DIR"

printf '\n\033[1;32m==> Workbook uploaded.\033[0m\n\n'
cat <<'EOF'
Check it landed:

    railway ssh -- ls -lh /data

Then open your site and submit a test application to confirm it works.
EOF
