#!/usr/bin/env bash
# Build the platmon image from this checkout and run it with Docker Compose; on Jetson the nvpmodel
# mounts (compose.jetson.yaml) are added automatically. Run it again after a git pull to update.
#   scripts/docker/start.sh
set -euo pipefail

cd "$(dirname "$0")/../.."

# both ways serve port 9797; use one at a time. A systemd service that is only stopped but still
# enabled would take the port back at the next boot, so it has to be removed (or disabled) first.
if systemctl is-active --quiet platmon 2>/dev/null || systemctl is-enabled --quiet platmon 2>/dev/null; then
    echo "platmon is installed as a systemd service (running or enabled at boot); remove it first:" >&2
    echo "  scripts/systemd/uninstall.sh   (or keep it installed but off: sudo systemctl disable --now platmon)" >&2
    exit 1
fi

files=(-f compose.yaml)
if [ -e /var/lib/nvpmodel/status ] && [ -e /etc/nvpmodel.conf ]; then
    files+=(-f compose.jetson.yaml)
    echo "Jetson: adding compose.jetson.yaml"
fi
docker compose "${files[@]}" up -d --build

echo "waiting for the health check..."
container=$(docker compose "${files[@]}" ps -q platmon)
state=starting
for _ in $(seq 30); do
    state=$(docker inspect -f '{{.State.Health.Status}}' "$container")
    case $state in
        healthy)
            docker compose "${files[@]}" logs --no-log-prefix --tail 2
            echo "platmon is up on port 9797 (restarts with Docker at boot)"
            exit 0 ;;
        unhealthy) break ;;
    esac
    sleep 2
done
echo "platmon is not healthy ($state); recent log:" >&2
docker compose "${files[@]}" logs --tail 20 >&2
exit 1
