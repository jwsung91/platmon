#!/usr/bin/env bash
# Stop the platmon systemd service and keep it from starting at boot.
#   scripts/systemd/stop.sh              stop and disable; installed files stay
#   scripts/systemd/stop.sh --uninstall  also remove /opt/platmon and the unit (the config in /etc/platmon stays)
set -euo pipefail

case "${1:-}" in
    "" | --uninstall) ;;
    *) echo "usage: $0 [--uninstall]" >&2; exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

unit=/etc/systemd/system/platmon.service
if [ -f "$unit" ]; then
    systemctl disable --now --quiet platmon
    echo "platmon service stopped and disabled"
else
    echo "platmon service is not installed"
fi

if [ "${1:-}" = --uninstall ]; then
    rm -f "$unit"
    systemctl daemon-reload
    rm -rf /opt/platmon
    echo "removed $unit and /opt/platmon; config kept in /etc/platmon"
fi
