#!/usr/bin/env bash
# Stop platmon, disable it at boot and remove the installed code and unit.
#   scripts/systemd/uninstall.sh          keeps the config in /etc/platmon for a later install
#   scripts/systemd/uninstall.sh --purge  removes /etc/platmon too
set -euo pipefail

case "${1:-}" in
    "" | --purge) ;;
    *) echo "usage: $0 [--purge]" >&2; exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

unit=/etc/systemd/system/platmon.service
if [ -f "$unit" ]; then
    systemctl disable --now --quiet platmon
    rm -f "$unit"
    systemctl daemon-reload
fi
rm -rf /opt/platmon
echo "platmon service removed (unit and /opt/platmon)"

if [ "${1:-}" = --purge ]; then
    rm -rf /etc/platmon
    echo "removed /etc/platmon"
else
    echo "config kept in /etc/platmon (--purge removes it)"
fi
