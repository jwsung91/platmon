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
# remember the container before "up" to report what compose did. It recreates the container when the
# rebuilt image or the config differs; some setups (e.g. Docker Desktop) get a new image id on every build.
before=$(docker compose "${files[@]}" ps -aq platmon)
was_running=false
if [ -n "$before" ]; then
    was_running=$(docker inspect -f '{{.State.Running}}' "$before")
fi

docker compose "${files[@]}" up -d --build

container=$(docker compose "${files[@]}" ps -q platmon)
if [ -z "$before" ]; then
    change="started: new container"
elif [ "$container" != "$before" ]; then
    change="updated: container recreated with the rebuilt image or changed config"
elif [ "$was_running" = true ]; then
    change="unchanged: running container kept (same image and config)"
else
    change="started: existing container was stopped"
fi
echo "$change"

echo "waiting for the health check..."
state=starting
for _ in $(seq 30); do
    state=$(docker inspect -f '{{.State.Health.Status}}' "$container")
    case $state in
        healthy)
            docker compose "${files[@]}" logs --no-log-prefix --tail 2
            echo "platmon is up on port 9797 (restarts with Docker at boot) - $change"
            exit 0 ;;
        unhealthy) break ;;
    esac
    sleep 2
done
echo "platmon is not healthy ($state); recent log:" >&2
docker compose "${files[@]}" logs --tail 20 >&2
exit 1
