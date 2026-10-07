"""Helpers for reading /proc and /sys, shared by the common and board-specific collectors."""
import glob
import os
import re

# Host paths a container cannot see at their usual place (Docker hides /sys/firmware and has its own /).
# Point them at bind mounts there; see compose.yaml.
DEVICE_TREE = os.environ.get("PLATMON_DEVICE_TREE", "/proc/device-tree")
HOST_ROOT = os.environ.get("PLATMON_HOST_ROOT", "/")  # the host's / : disk usage, /etc/os-release, ...


def host_path(path):
    """path on the host's root filesystem (unchanged outside a container)."""
    return os.path.join(HOST_ROOT, path.lstrip("/"))


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path, default=None):
    v = read(path)
    return int(v) if v else default


def numbered(d, pattern):
    """Sorted channel numbers N of files like temp{N}_input matching pattern in d."""
    return sorted(int(re.search(r"(\d+)_", os.path.basename(p)).group(1)) for p in glob.glob(f"{d}/{pattern}"))


def hwmon_chips(root="/sys/class/hwmon"):
    """(dir, chip name) for every hwmon device."""
    return [(d, read(f"{d}/name", "")) for d in sorted(glob.glob(f"{root}/hwmon*"))]
