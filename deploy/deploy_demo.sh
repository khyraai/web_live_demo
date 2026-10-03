#!/usr/bin/env bash
# ==============================================================================
# deploy_demo.sh — Full deployment script for the Khyra Website Live Demo
# ------------------------------------------------------------------------------
# Run this on your VPS (87.76.199.44) after SSHing in as root or sudo user.
#
# What it does:
#   1. Installs Nginx + certbot (if not already there)
#   2. Opens firewall ports 80 + 443
#   3. Syncs the code to /opt/voice-agent
#   4. Installs Python deps in the existing venv
#   5. Installs + starts the khyra-demo.service systemd unit
#   6. Writes the Nginx vhost config
#   7. Obtains a Let's Encrypt SSL certificate for khyraai.demo
#   8. Reloads Nginx
#
# Usage (from your LOCAL Windows machine with WSL/Git Bash, or from the VPS):
#
#   # From local machine — syncs code then runs deploy on server:
#   bash deploy/deploy_demo.sh --from-local
#
#   # From inside the VPS (after you've copied the repo to /opt/voice-agent):
#   sudo bash /opt/voice-agent/deploy/deploy_demo.sh
#
# Prerequisites:
#   - khyraai.demo DNS A record pointing to 87.76.199.44
#   - The repo is already at /opt/voice-agent (or use --from-local)
# ==============================================================================
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
VPS_IP="87.76.199.44"
VPS_USER="root"                   # change to your SSH user if not root
DOMAIN="khyraai.demo"
APP_DIR="/opt/voice-agent"
VENV="${APP_DIR}/.venv"
NGINX_AVAILABLE="/etc/nginx/sites-available/khyraai-demo"
NGINX_ENABLED="/etc/nginx/sites-enabled/khyraai-demo"
CERTBOT_EMAIL="manoj@khyraai.com"  # ← EDIT: your email for Let's Encrypt alerts
SERVICE_NAME="khyra-demo"

say() { echo -e "\n\033[1;36m==>\033[0m $*"; }
ok()  { echo -e "  \033[1;32m✔\033[0m  $*"; }
warn(){ echo -e "  \033[1;33m⚠\033[0m  $*"; }

# ── From-local mode: rsync + ssh ──────────────────────────────────────────────
if [[ "${1:-}" == "--from-local" ]]; then
  say "Syncing code to ${VPS_USER}@${VPS_IP}:${APP_DIR}…"
  rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
    ./ "${VPS_USER}@${VPS_IP}:${APP_DIR}/"
  say "Running deploy script on remote server…"
  ssh "${VPS_USER}@${VPS_IP}" "sudo bash ${APP_DIR}/deploy/deploy_demo.sh"
  say "Done! Test: curl -I https://${DOMAIN}/api/health"
  exit 0
fi

# ── Sanity: must be run on the server ─────────────────────────────────────────
if [[ "$(hostname -I | awk '{print $1}')" != "${VPS_IP}" ]]; then
  warn "This script should run ON the server (${VPS_IP}), not locally."
  warn "Use: bash deploy/deploy_demo.sh --from-local"
  exit 1
fi

# ── 1. Install Nginx + certbot ────────────────────────────────────────────────
say "Installing Nginx and certbot…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

# ── 2. Firewall: open 80 + 443 ────────────────────────────────────────────────
say "Opening firewall ports 80 and 443…"
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ok "Ports 80 and 443 open"

# ── 3. Python deps ────────────────────────────────────────────────────────────
say "Installing Python dependencies…"
if [ ! -d "${VENV}" ]; then
  python3.11 -m venv "${VENV}"
fi
"${VENV}/bin/pip" install --upgrade pip -q
"${VENV}/bin/pip" install -r "${APP_DIR}/requirements.txt" -q
ok "Python deps installed"

# ── 4. Create logs dir ────────────────────────────────────────────────────────
mkdir -p "${APP_DIR}/logs"
ok "Logs directory ready"

# ── 5. Install systemd service ────────────────────────────────────────────────
say "Installing ${SERVICE_NAME}.service…"
cp "${APP_DIR}/deploy/khyra-demo.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
sleep 2
systemctl is-active --quiet "${SERVICE_NAME}" && ok "${SERVICE_NAME} is running" || {
  warn "${SERVICE_NAME} failed to start — check: journalctl -u ${SERVICE_NAME} -n 30"
  exit 1
}

# ── 6. Nginx vhost ────────────────────────────────────────────────────────────
say "Writing Nginx vhost for ${DOMAIN}…"

# Temporarily write an HTTP-only config for the ACME challenge
cat > "${NGINX_AVAILABLE}" <<'NGINX_HTTP'
server {
    listen 80;
    listen [::]:80;
    server_name khyraai.demo;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
NGINX_HTTP

mkdir -p /var/www/certbot

# Enable the site
[ -L "${NGINX_ENABLED}" ] && rm "${NGINX_ENABLED}"
ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
nginx -t && systemctl reload nginx
ok "Nginx HTTP vhost active"

# ── 7. Let's Encrypt certificate ──────────────────────────────────────────────
say "Obtaining SSL certificate for ${DOMAIN}…"
echo ""
echo "  ⚠  Make sure ${DOMAIN} DNS A record → ${VPS_IP} BEFORE continuing."
echo "     (Check: dig +short ${DOMAIN})"
echo "  Press ENTER once DNS is confirmed, or Ctrl-C to abort."
read -r

certbot certonly \
  --nginx \
  --non-interactive \
  --agree-tos \
  --email "${CERTBOT_EMAIL}" \
  -d "${DOMAIN}" \
  --redirect || {
    warn "certbot failed. DNS may not have propagated yet."
    warn "Retry manually: certbot --nginx -d ${DOMAIN}"
    exit 1
  }
ok "SSL certificate obtained"

# ── 8. Write full HTTPS Nginx config ──────────────────────────────────────────
say "Writing full HTTPS Nginx vhost…"
cp "${APP_DIR}/deploy/khyraai-demo.nginx.conf" "${NGINX_AVAILABLE}"
nginx -t && systemctl reload nginx
ok "HTTPS vhost active"

# ── 9. Auto-renew cron ────────────────────────────────────────────────────────
say "Setting up certbot auto-renew…"
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'") \
  | sort -u | crontab -
ok "Auto-renew cron installed (runs daily at 3 AM)"

# ── Done ──────────────────────────────────────────────────────────────────────
say "Deployment complete!"
echo ""
echo "  WebSocket:  wss://${DOMAIN}/ws"
echo "  Health:     https://${DOMAIN}/api/health"
echo "  Test page:  https://${DOMAIN}/static/demo_test.html"
echo ""
echo "  Service logs:  journalctl -u ${SERVICE_NAME} -f"
echo "  Nginx logs:    tail -f /var/log/nginx/error.log"
