"""platmon core: collect() returns one dict of board status. No HTTP or output code.

common.collect() fills the fields every Linux host has; the detected board's module,
if any, fills its own optional fields through extend(stats). Viewers never branch on the board.
"""
import os

from . import common, jetson, sysfs
from .sampler import Collected
from .sysfs import DEVICE_TREE, pointer, read

REQUIRED_READS = ("cpu", "memory", "disk", "uptime")

BOARDS = (  # (device-tree compatible match, display name, board module or None)
    ("nvidia,tegra234", "Jetson Orin", jetson),
    ("nvidia,tegra194", "Jetson Xavier", jetson),
    ("nvidia,tegra", "Jetson", jetson),
    ("raspberrypi", "Raspberry Pi", None),
)


def detect(compatible, has_dmi):
    """compatible: <device tree>/compatible (NUL-separated), empty on x86."""
    for key, name, module in BOARDS:
        if key in compatible:
            return name, module
    return ("PC" if has_dmi else "Linux"), None


PLATFORM, BOARD = detect(read(f"{DEVICE_TREE}/compatible", ""), os.path.isdir("/sys/class/dmi/id"))


def collect(cpu=None, logged=None):
    """cpu: a common.CpuCounters kept between calls (the service); None for a one-off reading.
    logged: a dict the service keeps between calls, so lasting read problems are logged once (sysfs.summarize).
    stats["collectors"] has the optional groups' state; the Sampler adds "core"."""
    return _collect(cpu, logged, None)[0]


def collect_recorded(cpu, logged, clock):
    """The service's collect(): the same stats, plus for the Sampler where each sensor value came from and
    when it and the required data were read (all on clock, the Sampler's and cpu's elapsed clock)."""
    trace = sysfs.Trace(clock)
    stats, groups = _collect(cpu, logged, trace)
    sensors, targets = sensor_entries(stats, groups)
    return Collected(stats, sensors, {name: trace.required.get(name) for name in REQUIRED_READS}, targets, clock)


def sensor_entries(stats, groups):
    """({JSON Pointer: metadata} for the sensor values in the final stats, [pointers of every value that
    needs a record]). Pointers come from the output itself, so they follow label fallbacks, duplicate names
    and the fan list as they ended up; a value left out gets no pointer, a null one no read. The Sampler
    checks the two against each other and the stats."""
    out, targets = {}, []

    def add(ptr, info, value):
        targets.append(ptr)
        if info is not None:
            out[ptr] = info if value is not None else {**info, "span": None}

    for table in ("temperature", "power"):
        for key, value in stats[table].items():
            add(pointer(table, key), groups[table].sensors.get(key), value)
    for i, fan in enumerate(stats["fans"]):
        for field in ("rpm", "percent"):
            add(pointer("fans", i, field), groups["fans"].sensors.get((id(fan), field)), fan[field])
    for i, c in enumerate(stats["cpu"]):  # i is the position in this list, c["id"] the CPU
        add(pointer("cpu", i, "freq"), groups["cpu_frequency"].sensors.get(c["id"]), c["freq"])
    if isinstance(stats["gpu"], dict):
        for field in ("usage", "freq", "max_freq"):
            add(pointer("gpu", field), groups["gpu"].sensors.get(field), stats["gpu"].get(field))
    return out, targets


def _collect(cpu, logged, trace):
    groups = sysfs.groups(trace=trace)
    stats = {"platform": PLATFORM, **common.collect(cpu, groups, trace)}
    if BOARD:
        BOARD.extend(stats, groups)
    else:  # no board module: nothing on this platform provides these
        for name in ("gpu", "power_mode", "board_info"):
            groups[name].note(name, "unsupported_platform")
    stats["collectors"] = sysfs.summarize(groups, logged)
    return stats, groups
