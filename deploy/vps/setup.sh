#!/usr/bin/env bash
# Lokamania 09 — one-time server setup. Run as root on a fresh Ubuntu VPS.
#
#   sudo bash setup.sh
#
# Installs: Python venv + gunicorn, Caddy, systemd service, firewall,
#           daily backups. Safe to re-run — it will not overwrite your
#           .env file or your workbook.
set -euo pipefail

APP_USER="${APP_USER:-lokamania}"
APP_DIR="${APP_DIR:-/opt/lokamania}"
DATA_DIR="${DATA_DIR:-/srv/lokamania-data}"
BACKUP_DIR="$DATA_DIR/backups"
WORKBOOK="$DATA_DIR/Lokamania_09_Brand_Applications_FINAL.xlsx"
# Normally setup.sh lives in the project's deploy/ folder. When upload.sh
# pipes it over SSH it passes DEPLOY_DIR explicitly instead.
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]:-setup.sh}")" && pwd)}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root:   sudo bash setup.sh"
[ -d "$DEPLOY_DIR" ] || die "setup.sh must live in the deploy/ folder of the project"

export DEBIAN_FRONTEND=noninteractive

step "1/9  Updating the operating system"
apt-get update -qq
apt-get upgrade -y -qq

step "2/9  Installing base packages"
apt-get install -y -qq \
  curl ca-certificates git rsync unzip ufw fail2ban \
  python3 python3-venv python3-pip

step "3/9  Creating the unprivileged app user and folders"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /usr/bin/bash "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$BACKUP_DIR"
[ -d "$APP_DIR" ] || install -d -o "$APP_USER" -g "$APP_USER" -m 755 "$APP_DIR"

step "4/9  Installing Caddy (web server + automatic HTTPS)"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi
caddy version

step "5/9  Installing the Python application into $APP_DIR"
[ -f "$APP_DIR/server/app.py" ] || die "Application code not found in $APP_DIR — run deploy/upload.sh first"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/server/.venv"
sudo -u "$APP_USER" "$APP_DIR/server/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/server/.venv/bin/pip" install --quiet -r "$APP_DIR/server/requirements.txt"

step "6/9  Verifying the workbook (the database)"
if [ ! -f "$WORKBOOK" ]; then
  die "Workbook not found at $WORKBOOK — upload it with deploy/upload.sh, then re-run setup.sh"
fi
chown "$APP_USER:$APP_USER" "$WORKBOOK"
chmod 640 "$WORKBOOK"
printf '    workbook: %s (%s)\n' "$WORKBOOK" "$(du -h "$WORKBOOK" | cut -f1)"

step "7/9  Creating .env if it is missing"
if [ -f "$APP_DIR/.env" ]; then
  echo "    .env already exists — leaving it untouched."
else
  SECRET_KEY="$(head -c 32 /dev/urandom | base64 | tr -d '\n/+=' | head -c 40)"
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(head -c 18 /dev/urandom | base64 | tr -d '\n/+=' | head -c 20)}"
  umask 077
  cat > "$APP_DIR/.env" <<EOF
# Lokamania 09 — server configuration. Treat this file as a password.
ADMIN_PASSWORD=$ADMIN_PASSWORD
SECRET_KEY=$SECRET_KEY
EXCEL_PATH=$WORKBOOK
PORT=8000
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 640 "$APP_DIR/.env"
  echo "    New .env written. Admin password: $ADMIN_PASSWORD"
fi

step "8/9  Installing the systemd service, Caddy config and backup job"
install -m 644 "$DEPLOY_DIR/lokamania.service" /etc/systemd/system/lokamania.service
install -m 644 "$DEPLOY_DIR/Caddyfile"       /etc/caddy/Caddyfile
install -m 755 "$DEPLOY_DIR/backup.sh"       /usr/local/sbin/lokamania-backup

cat > /etc/cron.d/lokamania-backup <<'EOF'
# Lokamania 09 — snapshot the workbook every day at 03:17
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 3 * * * lokamania /usr/local/sbin/lokamania-backup >> /var/log/lokamania-backup.log 2>&1
EOF
chmod 644 /etc/cron.d/lokamania-backup

systemctl daemon-reload
systemctl enable --now lokamania.service
systemctl reload caddy || systemctl restart caddy
echo "    lokamania.service enabled, Caddy reloaded."

step "9/9  Turning on the firewall and SSH brute-force protection"
ufw --force reset >/dev/null
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH   >/dev/null   # 22
ufw allow 80/tcp     >/dev/null
ufw allow 443/tcp    >/dev/null
ufw allow 443/udp    >/dev/null   # HTTP/3
ufw --force enable   >/dev/null
systemctl enable --now fail2ban >/dev/null 2>&1 || echo "    (fail2ban not started — not critical)"

printf '\n\033[1;32m==> Setup complete.\033[0m\n'
cat <<'EOF'

Check it is healthy:

    systemctl status lokamania --no-pager
    curl -s http://127.0.0.1:8000/api/health

If you are using Cloudflare, set the DNS A record for your domain to this
server's public IPv4 address now.
EOF
