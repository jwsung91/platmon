"""Helpers for reading /proc and /sys, shared by the common and board-specific collectors."""
import contextlib
import errno
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


def entries(path, *groups, listed=False):
    """Sorted names in directory path. A directory that is not there is empty; any other listing error is
    noted in groups (target: the directory's name) and gives [], so it is not taken for "nothing there".
    listed: path itself was found by listing in this collection, so its absence means it disappeared."""
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        if listed:
            for g in groups:
                g.note(os.path.basename(path), "disappeared")
        return []
    except OSError as e:
        for g in groups:
            g.note(os.path.basename(path), reason_of(e), f"{path}: {e.strerror}")
        return []


def numbered(names, prefix, suffix):
    """Sorted channel numbers N of names like prefix{N}suffix (temp{N}_input) among a directory's names."""
    return sorted(int(m.group(1)) for n in names if (m := re.fullmatch(rf"{prefix}(\d+){suffix}", n)))


def hwmon_chips(root="/sys/class/hwmon", *groups):
    """(dir, chip name) for every hwmon device. A class directory that cannot be listed, or a name that cannot
    be read, is noted in groups; such a chip is named after its directory (hwmon2) and still read."""
    chips = []
    for n in entries(root, *groups):
        if re.fullmatch(r"hwmon\d+", n):
            d = f"{root}/{n}"
            name = Group("name")
            chips.append((d, name.read(f"{d}/name", f"{n}.name", parse=str, found=d) or n))
            for g in groups:
                g.merge(name)
    return chips


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

    def merge(self, other):
        """Takes over what another Group noted (e.g. one shared read, or candidates that all failed)."""
        self.reasons |= other.reasons
        for issue, detail in zip(other.issues, other.details):
            if len(self.issues) < MAX_ISSUES:
                self.issues.append(issue)
                self.details.append(detail)
            else:
                self.truncated += 1
        self.truncated += other.truncated

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
        except UnicodeDecodeError:  # bytes that are not text cannot be a number either
            return self.note(target, "invalid_data", path)
        except FileNotFoundError:
            gone = found is not None and not os.path.exists(found)
            return self.note(target, "disappeared" if gone else "not_exposed")
        except OSError as e:
            return self.note(target, reason_of(e), f"{path}: {e.strerror}")
        try:
            return parse(text)
        except ValueError:  # int("") included: an empty number is not 0
            return self.note(target, "invalid_data", path)

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
