#!/usr/bin/env bash
#
# Deploy psa-proxy to a Proxmox LXC/VM.
#
# Prerequisites:
#   - SSH access to the target host
#   - Cloudflare Tunnel already configured and pointing to http://localhost:3001
#
# Usage:
#   ./mcp/deploy-proxmox.sh <host> [api-key]
#
# Examples:
#   ./mcp/deploy-proxmox.sh root@192.168.1.50 my-secret-key
#   ./mcp/deploy-proxmox.sh psa-proxy.local          # prompts for key

set -euo pipefail

HOST="${1:?Usage: $0 <ssh-host> [api-key]}"
API_KEY="${2:-}"

if [ -z "$API_KEY" ]; then
  read -rsp "PSA_PROXY_API_KEY: " API_KEY
  echo
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/opt/psa-proxy"

echo "==> Installing system dependencies on $HOST..."
ssh "$HOST" "apt-get update -qq && apt-get install -y -qq python3 python3-venv curl wget tar > /dev/null"

echo "==> Installing curl-impersonate (Chrome TLS fingerprint)..."
ssh "$HOST" bash -s <<'IMPERSONATE'
set -e
if command -v curl_chrome116 >/dev/null 2>&1; then
  echo "curl-impersonate already installed"
  exit 0
fi
ARCH=$(uname -m)
URL="https://github.com/lwthiker/curl-impersonate/releases/download/v0.6.1/curl-impersonate-v0.6.1.${ARCH}-linux-gnu.tar.gz"
cd /tmp
wget -q "$URL" -O curl-impersonate.tar.gz
tar xzf curl-impersonate.tar.gz -C /usr/local/bin/
chmod +x /usr/local/bin/curl_chrome* /usr/local/bin/curl_ff* 2>/dev/null || true
rm curl-impersonate.tar.gz
curl_chrome116 --version | head -1
IMPERSONATE

echo "==> Creating service user and directory..."
ssh "$HOST" bash -s <<'SETUP'
id -u psa-proxy &>/dev/null || useradd -r -s /usr/sbin/nologin psa-proxy
mkdir -p /opt/psa-proxy
chown psa-proxy:psa-proxy /opt/psa-proxy
SETUP

echo "==> Uploading proxy files..."
scp -q \
  "$SCRIPT_DIR/psa_proxy.py" \
  "$SCRIPT_DIR/centering.py" \
  "$SCRIPT_DIR/psa-proxy.service" \
  "$HOST:$REMOTE_DIR/"

echo "==> Writing .env..."
ssh "$HOST" "cat > $REMOTE_DIR/.env <<EOF
PSA_PROXY_API_KEY=$API_KEY
EOF
chmod 600 $REMOTE_DIR/.env
chown psa-proxy:psa-proxy $REMOTE_DIR/.env"

echo "==> Setting up Python venv + Pillow + Playwright..."
ssh "$HOST" bash -s <<'VENV'
cd /opt/psa-proxy
if [ ! -d venv ]; then
  python3 -m venv venv
fi
venv/bin/pip install -q --upgrade pip Pillow playwright
# Install chromium + its system dependencies (one-time, ~400MB)
venv/bin/playwright install --with-deps chromium
VENV

echo "==> Installing and starting systemd service..."
ssh "$HOST" bash -s <<'SVC'
cp /opt/psa-proxy/psa-proxy.service /etc/systemd/system/
chown root:root /etc/systemd/system/psa-proxy.service
systemctl daemon-reload
systemctl enable psa-proxy
systemctl restart psa-proxy
sleep 1
systemctl status psa-proxy --no-pager
SVC

echo "==> Verifying health endpoint..."
ssh "$HOST" "curl -sf http://localhost:3001/health" && echo " OK" || echo " FAILED"

echo ""
echo "Done. The proxy is running on $HOST:3001."
echo "Make sure your Cloudflare Tunnel ingress routes to http://localhost:3001."
