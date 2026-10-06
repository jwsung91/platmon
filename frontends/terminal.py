"""Terminal frontend: redraws the core's latest snapshot on this process's terminal."""
import sys
import threading
import time

from .cli import render


def start(sampler, cfg=None):
    """cfg: the [terminal] config section (no options yet). Skipped without a TTY, e.g. under systemd."""
    if not sys.stdout.isatty():
        print("platmon: terminal frontend skipped, stdout is not a terminal", file=sys.stderr)
        return None

    def run():
        while True:
            stats = sampler.latest()
            text = render(stats) if stats else "no current data: not collected yet, or collection keeps failing (see stderr)"
            print("\033[H\033[J" + text, flush=True)
            time.sleep(sampler.interval)

    t = threading.Thread(target=run, name="terminal", daemon=True)
    t.start()
    return t
