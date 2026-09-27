#!/bin/sh
# Idempotent installer; run on the Pi as root from /opt/treadmill-bridge/bridge.
set -eu
cd "$(dirname "$0")/.."
id treadmill >/dev/null 2>&1 || useradd --system --home /var/lib/treadmill-bridge --shell /usr/sbin/nologin treadmill
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
UV_PYTHON_PREFERENCE=only-system uv sync --frozen --no-dev
install -d -m 0750 -o root -g treadmill /etc/treadmill-bridge
if [ ! -f /etc/treadmill-bridge/config.toml ]; then
    token=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
    sed "s/CHANGE_ME/$token/" deploy/config.example.toml > /etc/treadmill-bridge/config.toml
    chown root:treadmill /etc/treadmill-bridge/config.toml
    chmod 0640 /etc/treadmill-bridge/config.toml
fi
install -d -m 0750 -o treadmill -g treadmill /var/lib/treadmill-bridge
chmod 0755 deploy/prepare-radios.sh
systemctl disable --now bluetooth.service 2>/dev/null || true
install -m 0644 deploy/treadmill-bridge.service /etc/systemd/system/treadmill-bridge.service
systemctl daemon-reload
systemctl enable treadmill-bridge.service
systemctl restart treadmill-bridge.service
