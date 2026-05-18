#!/usr/bin/env bash
#
# Bootstrap a fresh Ubuntu 22.04+ / 24.04 VM (any cloud) to run the wedding
# photo sharing app. Idempotent — safe to re-run after edits or updates.
#
# Usage on a fresh VM:
#   sudo apt-get update && sudo apt-get install -y git
#   sudo git clone https://github.com/<you>/wedding-photo-sharing.git /opt/wedding
#   cd /opt/wedding
#   sudo bash deploy/bootstrap.sh
#
# Then edit /opt/wedding/backend/.env with your credentials and run:
#   sudo -u wedding pm2 restart all

set -euo pipefail

# ─── Configurable ────────────────────────────────────────────────────────────
SERVICE_USER="${SERVICE_USER:-wedding}"
APP_DIR="${APP_DIR:-/opt/wedding}"
LOG_DIR="/var/log/wedding"
NODE_MAJOR="20"

# ─── Helpers ─────────────────────────────────────────────────────────────────
log()  { echo -e "\033[1;36m[bootstrap]\033[0m $*"; }
warn() { echo -e "\033[1;33m[bootstrap]\033[0m $*" >&2; }
die()  { echo -e "\033[1;31m[bootstrap]\033[0m $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash deploy/bootstrap.sh"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO_DIR/package.json" ]] || die "Could not locate repo root from $REPO_DIR"

# Ubuntu/Debian only for now — sanity check
command -v apt-get >/dev/null || die "This script targets Debian/Ubuntu (apt). Adapt for your distro."

# ─── 1. System packages ──────────────────────────────────────────────────────
log "Updating apt index"
DEBIAN_FRONTEND=noninteractive apt-get update -qq

log "Installing base packages (nginx, curl, ca-certificates, git)"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  nginx curl ca-certificates git build-essential

# ─── 2. Node.js ──────────────────────────────────────────────────────────────
if command -v node >/dev/null && node -v | grep -q "^v${NODE_MAJOR}\."; then
  log "Node.js $(node -v) already installed"
else
  log "Installing Node.js ${NODE_MAJOR}.x from NodeSource"
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs
fi

# ─── 3. PM2 ──────────────────────────────────────────────────────────────────
if ! command -v pm2 >/dev/null; then
  log "Installing PM2"
  npm install -g pm2
else
  log "PM2 already installed ($(pm2 -v))"
fi

# ─── 4. Service user ─────────────────────────────────────────────────────────
if id "$SERVICE_USER" &>/dev/null; then
  log "Service user '$SERVICE_USER' already exists"
else
  log "Creating service user '$SERVICE_USER'"
  useradd --system --create-home --shell /bin/bash "$SERVICE_USER"
fi

# ─── 5. Place repo at APP_DIR ────────────────────────────────────────────────
if [[ "$REPO_DIR" != "$APP_DIR" ]]; then
  if [[ -L "$APP_DIR" && "$(readlink "$APP_DIR")" == "$REPO_DIR" ]]; then
    log "$APP_DIR -> $REPO_DIR symlink already in place"
  elif [[ -e "$APP_DIR" ]]; then
    warn "$APP_DIR exists and is not the expected symlink — leaving alone"
  else
    log "Symlinking $APP_DIR -> $REPO_DIR"
    ln -s "$REPO_DIR" "$APP_DIR"
  fi
fi

# ─── 6. Permissions ──────────────────────────────────────────────────────────
log "Chowning $REPO_DIR to $SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR"

log "Creating log directory $LOG_DIR"
mkdir -p "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"

# ─── 7. .env (copy from template if missing) ─────────────────────────────────
ENV_FILE="$REPO_DIR/backend/.env"
if [[ -f "$ENV_FILE" ]]; then
  log "$ENV_FILE already exists — leaving alone"
else
  log "Copying env template to $ENV_FILE"
  cp "$REPO_DIR/deploy/.env.template" "$ENV_FILE"
  chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ENV_NEEDS_EDIT=1
fi

# ─── 8. npm ci + build (as service user) ─────────────────────────────────────
log "Installing dependencies (npm ci)"
sudo -u "$SERVICE_USER" -H bash -c "cd '$REPO_DIR' && npm ci"

log "Building all workspaces"
sudo -u "$SERVICE_USER" -H bash -c "cd '$REPO_DIR' && npm run build"

# ─── 9. Nginx site ───────────────────────────────────────────────────────────
log "Installing Nginx site config"
cp "$REPO_DIR/deploy/nginx/wedding.conf" /etc/nginx/sites-available/wedding
ln -sf /etc/nginx/sites-available/wedding /etc/nginx/sites-enabled/wedding
rm -f /etc/nginx/sites-enabled/default

log "Testing Nginx config"
nginx -t

log "Reloading Nginx"
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

# ─── 10. PM2 — start, save, enable on boot ───────────────────────────────────
log "Starting PM2 processes as $SERVICE_USER"
sudo -u "$SERVICE_USER" -H bash -c "cd '$REPO_DIR' && pm2 startOrReload deploy/ecosystem.config.cjs"
sudo -u "$SERVICE_USER" -H bash -c "pm2 save"

log "Installing systemd unit so PM2 starts on boot"
# pm2 startup, run as root, generates and installs the unit for the service user.
env PATH="$PATH:/usr/bin" pm2 startup systemd \
  -u "$SERVICE_USER" --hp "/home/$SERVICE_USER" >/dev/null

# ─── Done ────────────────────────────────────────────────────────────────────
echo
log "Bootstrap complete."
echo
echo "Next steps:"
if [[ "${ENV_NEEDS_EDIT:-0}" == "1" ]]; then
  echo "  1. Edit $ENV_FILE with your real credentials:"
  echo "       sudo -u $SERVICE_USER \${EDITOR:-vi} $ENV_FILE"
  echo "  2. Restart the apps so they pick up the new env:"
  echo "       sudo -u $SERVICE_USER pm2 restart all"
  echo "  3. Verify with: sudo -u $SERVICE_USER pm2 status && pm2 logs"
else
  echo "  - Verify with: sudo -u $SERVICE_USER pm2 status"
  echo "  - Tail logs:   sudo -u $SERVICE_USER pm2 logs"
fi
echo
echo "App is reachable on http://<vm-public-ip>/  (Nginx listening on :80)"
