#!/usr/bin/env bash
# Install or update platmon as a systemd service from this checkout, enable it at boot and start it.
#   scripts/systemd/install.sh        (run it again after a git pull to update)
# Code:   /opt/platmon                       replaced on every run
# Config: /etc/platmon/platmon.ini           created once from platmon.ini, never overwritten
# Unit:   /etc/systemd/system/platmon.service
set -euo pipefail

[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
prefix=/opt/platmon
config=/etc/platmon/platmon.ini
unit=/etc/systemd/system/platmon.service

# both ways serve port 8080; use one at a time
if command -v docker >/dev/null && [ -n "$(docker ps -q --filter label=com.docker.compose.project=platmon 2>/dev/null)" ]; then
    echo "platmon is running in Docker; stop it first: scripts/docker/stop.sh" >&2
    exit 1
fi

if [ -f "$config" ]; then
    echo "keeping existing config $config"
else
    install -D -m 644 "$repo/platmon.ini" "$config"
    echo "created config $config"
fi
# check the config with this checkout's code before replacing anything
python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from platmon import load_config
try:
    load_config(sys.argv[2])
except ValueError as e:
    sys.exit(f"invalid config: {e}")
' "$repo" "$config"

echo "installing code to $prefix"
rm -rf "$prefix"
mkdir -p "$prefix"
cp -r "$repo/platmon.py" "$repo/collector" "$repo/frontends" "$prefix/"
find "$prefix" -name __pycache__ -prune -exec rm -rf {} +
chmod -R a+rX "$prefix"   # the service runs as an unprivileged DynamicUser

install -m 644 "$repo/platmon.service" "$unit"
systemctl daemon-reload
systemctl enable --quiet platmon
echo "enabled at boot"

exec "$here/start.sh"
