"""Wi-Fi signal, a low-frequency observation (collector/slow.py): what the kernel last knew about each
wireless interface's link, from /proc/net/wireless. Passive: no scan, no reconnect, no setting changed;
SSID, BSSID and nearby access points are never read. Contract: docs/wifi.md.

Format (net/wireless/wext-proc.c): "name: status link[.] level[.] noise[.] ...", where '.' marks a value
updated since the last read and level / noise are dBm (negative) when the driver reports dBm, otherwise a
value of unspecified unit; a noise of -256 is "not available".
"""
import re

from .network import valid_name
from .sysfs import reason_of

PROVIDER = "proc_net_wireless"
PATH = "/proc/net/wireless"
ROW = re.compile(r"\s*(\S+):\s+([0-9a-f]{4})\s+(-?\d+)(\.?)\s+(-?\d+)(\.?)\s+(-?\d+)(\.?)(?:\s+\d+){6}\s*")


def parse(text):
    """([interface], [(target, why)]). Rows that do not match the format are left out and reported."""
    lines = text.split("\n")
    if len(lines) < 2 or "Quality" not in lines[0] or "level" not in lines[1]:
        raise ValueError("unexpected header")
    out, bad = [], []
    for n, line in enumerate(lines[2:], 3):
        if not line.strip():
            continue
        m = ROW.fullmatch(line)
        if not m or not valid_name(m.group(1)):
            bad.append((f"line{n}", "invalid_data"))
            continue
        name, link, link_new, level, level_new, noise = m.group(1), int(m.group(3)), m.group(4), int(m.group(5)), \
            m.group(6), int(m.group(7))
        # cfg80211 updates link and level together whenever it has station data, i.e. while associated;
        # without it the interface is listed with nothing updated
        connected = bool(level_new)
        dbm = level < 0  # the kernel subtracts 256 for dBm values, so they come out negative
        out.append({"name": name, "connected": connected,
                    "signal_dbm": level if connected and dbm else None,
                    "signal_raw": level if connected and not dbm else None,  # a driver without dBm: unit unknown
                    "link_quality": link if connected and link_new else None,
                    "noise_dbm": noise if connected and noise < 0 and noise != -256 else None})
    return out, bad


class Wifi:
    """observe(group) for collector/slow.py."""

    def __init__(self, read=None):
        self._read = read or _read

    def __call__(self, group):
        out = {"scope": {"kind": "process_network_namespace"}, "provider": PROVIDER, "interfaces": []}
        try:
            interfaces, bad = parse(self._read(PATH))
        except FileNotFoundError:
            group.note("wireless", "not_exposed")  # no wireless extensions / cfg80211 compat in this kernel
            return out
        except OSError as e:
            group.note("wireless", reason_of(e), f"{PATH}: {e.strerror}")
            return out
        except (UnicodeDecodeError, ValueError):
            group.note("wireless", "invalid_data", PATH)
            return out
        for target, why in bad:
            group.note(target, why, PATH)
        out["interfaces"] = [group.got(i) for i in sorted(interfaces, key=lambda i: i["name"])]
        if not interfaces and not bad:
            group.note("wireless", "not_detected")  # the file is there, no wireless interface in it
        return out


def _read(path):
    with open(path, encoding="ascii") as f:
        return f.read()
