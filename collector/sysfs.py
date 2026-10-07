"""Helpers for reading /proc and /sys, shared by the common and board-specific collectors."""
import contextlib
import errno
import glob
import os
import re
import sys
import traceback

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


# Diagnostics of optional metrics (collectors.<group> in /api/stats). Reasons in PROBLEMS are read failures,
# most serious first; ABSENT ones say why there is no value without calling it an error, most specific first.
PROBLEMS = ("internal_error", "permission_denied", "io_error", "disappeared", "invalid_data")
ABSENT = ("no_data", "not_exposed", "not_detected", "unsupported_platform")
OPTIONAL = ("cpu_frequency", "gpu", "temperature", "power", "fans", "power_mode", "board_info")
MAX_ISSUES, MAX_TARGET = 32, 64


def reason_of(e):
    """The reason code of an OSError from reading or listing a sysfs/procfs entry."""
    if e.errno in (errno.EACCES, errno.EPERM):
        return "permission_denied"
    return "no_data" if e.errno == errno.ENODATA else "io_error"  # ENODATA: e.g. an inactive thermal zone


class Group:
    """One optional metric group in one collection: how many values it got, and why others are missing.
    Only the reason codes and short targets (e.g. "hwmon2.temp1") reach the API; paths and exception text
    go to the service log."""

    def __init__(self, name):
        self.name, self.values, self.reasons = name, 0, set()
        self.issues, self.truncated, self.details = [], 0, []

    def note(self, target, reason, detail=None):
        """Records why target has no value; returns None so a reader can return it."""
        self.reasons.add(reason)
        if reason in PROBLEMS:
            if len(self.issues) < MAX_ISSUES:
                self.issues.append({"target": target[:MAX_TARGET], "reason": reason})
                self.details.append(f"{target}: {reason}" + (f" ({detail})" if detail else ""))
            else:
                self.truncated += 1
        return None

    def got(self, value):
        """Counts a value the group reports."""
        self.values += 1
        return value

    def read(self, path, target, parse=int, found=None):
        """parse(content of path), or None with the reason noted. found: what this collection discovered by
        listing (the file itself, or its device directory); if that is gone too the file disappeared,
        otherwise the attribute is just not exposed."""
        try:
            with open(path) as f:
                text = f.read().strip()
        except FileNotFoundError:
            gone = found is not None and not os.path.exists(found)
            return self.note(target, "disappeared" if gone else "not_exposed")
        except OSError as e:
            return self.note(target, reason_of(e), f"{path}: {e.strerror}")
        try:
            return parse(text)
        except ValueError:  # int("") included: an empty number is not 0
            return self.note(target, "invalid_data", path)

    def listdir(self, root):
        """Notes why root could not be listed (glob would just return nothing); a missing root is "nothing here"."""
        try:
            os.listdir(root)
        except FileNotFoundError:
            pass
        except OSError as e:
            self.note(os.path.basename(root), reason_of(e), f"{root}: {e.strerror}")

    def status(self):
        problems = [r for r in PROBLEMS if r in self.reasons]
        if self.values:
            state, reason = ("partial", "some_unreadable") if problems else ("ok", None)
        elif problems:
            state, reason = "error", problems[0]
        else:  # nothing tried counts as nothing found, never as ok
            state, reason = "unavailable", next((r for r in ABSENT if r in self.reasons), "not_detected")
        return {"state": state, "reason": reason, "issues": list(self.issues), "issues_truncated": self.truncated}


@contextlib.contextmanager
def guard(*groups):
    """An unexpected exception inside one optional part becomes internal_error of its groups instead of
    failing the collection; the traceback goes to the log only."""
    try:
        yield
    except Exception:
        for g in groups:
            g.note(g.name, "internal_error", traceback.format_exc(limit=3).strip().replace("\n", " | "))


def groups(*names):
    return {n: Group(n) for n in names or OPTIONAL}


def summarize(groups, logged=None):
    """collectors entries of the groups. Their problems go to stderr when they change: logged is the
    service's {group: last details} kept between collections, so a lasting failure is logged once."""
    out = {}
    for g in groups.values():
        out[g.name] = g.status()
        details = tuple(g.details) + ((f"+{g.truncated} more",) if g.truncated else ())
        before = None if logged is None else logged.get(g.name, ())
        if details != before:
            if details:
                print(f"platmon: {g.name}: " + "; ".join(details), file=sys.stderr)
            elif before:
                print(f"platmon: {g.name}: readable again", file=sys.stderr)
            if logged is not None:
                logged[g.name] = details
    return out
