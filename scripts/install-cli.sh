#!/usr/bin/env bash
# Install the `platmon` command: the terminal client (frontends/cli.py, standard library only).
# Works on any machine with Python 3.9+, the device itself or a PC that watches it remotely.
#   scripts/install-cli.sh                    /usr/local/bin/platmon (asks for sudo)
#   scripts/install-cli.sh --user             ~/.local/bin/platmon (no sudo)
#   scripts/install-cli.sh --uninstall [--user]
# scripts/systemd/install.sh runs this too. Run it again after a git pull to update the command.
set -euo pipefail

usage() { echo "usage: $0 [--user] [--uninstall]" >&2; exit 2; }
dir=/usr/local/bin
uninstall=false
for arg in "$@"; do
    case $arg in
        --user) dir=$HOME/.local/bin ;;
        --uninstall) uninstall=true ;;
        *) usage ;;
    esac
done
target=$dir/platmon
src=$(cd "$(dirname "$0")/.." && pwd)/frontends/cli.py

if [ "$dir" = /usr/local/bin ] && [ "$(id -u)" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

# only ever replace or remove our own command
if [ -e "$target" ] && ! grep -q '^# platmon-cli:' "$target"; then
    echo "$target exists and is not the platmon client; leaving it alone" >&2
    exit 1
fi

if $uninstall; then
    rm -f "$target"
    echo "removed $target"
    exit 0
fi

mkdir -p "$dir"
install -m 755 "$src" "$target"
echo "installed $target"
case ":$PATH:" in
    *":$dir:"*) ;;
    *) echo "note: $dir is not in PATH; add it, or run $target" ;;
esac
