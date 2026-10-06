"""Helpers for reading /proc and /sys, shared by the common and board-specific collectors."""
import glob
import os
import re


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
