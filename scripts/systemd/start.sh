#!/usr/bin/env bash
# Install or update platmon as a systemd service from this checkout, then start it.
#   scripts/systemd/start.sh
# Code:   /opt/platmon                       replaced on every run
# Config: /etc/platmon/platmon.ini           created once from platmon.ini, never overwritten
# Unit:   /etc/systemd/system/platmon.service
set -euo pipefail

[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

repo=$(cd "$(dirname "$0")/../.." && pwd)
prefix=/opt/platmon
config=/etc/platmon/platmon.ini
unit=/etc/systemd/system/platmon.service

# both ways serve port 8080; run one at a time
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
# check the config with this checkout's code before replacing anything; prints "host port" for the check below
listen=$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from platmon import load_config
try:
    http = load_config(sys.argv[2])["http"]
except ValueError as e:
    sys.exit(f"invalid config: {e}")
print("127.0.0.1" if http["bind"] == "0.0.0.0" else http["bind"], http.getint("port"))
' "$repo" "$config")
read -r host port <<< "$listen"

echo "installing code to $prefix"
rm -rf "$prefix"
mkdir -p "$prefix"
cp -r "$repo/platmon.py" "$repo/collector" "$repo/frontends" "$prefix/"
find "$prefix" -name __pycache__ -prune -exec rm -rf {} +
chmod -R a+rX "$prefix"   # the service runs as an unprivileged DynamicUser

install -m 644 "$repo/platmon.service" "$unit"
systemctl daemon-reload
systemctl enable --quiet platmon
systemctl restart platmon

check='import sys, urllib.request; urllib.request.urlopen(f"http://{sys.argv[1]}:{sys.argv[2]}/api/stats", timeout=2)'
for _ in $(seq 20); do
    if python3 -c "$check" "$host" "$port" 2>/dev/null; then
        journalctl -u platmon -n 2 --no-pager -o cat
        echo "platmon is up on port $port (starts at boot)"
        exit 0
    fi
    sleep 0.5
done
echo "platmon did not answer on $host:$port; recent log:" >&2
journalctl -u platmon -n 20 --no-pager >&2
exit 1
