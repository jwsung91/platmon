# platmon

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="frontends/web/assets/brand/platmon-logo-dark.svg">
  <img src="frontends/web/assets/brand/platmon-logo-light.svg" alt="platmon" width="440">
</picture>

Lightweight platform monitor for Jetson, Raspberry Pi, PCs and other Linux hosts.
One collector core runs on the device as a background service with an HTTP API; a terminal client and a web page show what it collects.

- No dependencies: Python 3.9+ standard library only
- Reads `/proc` and `/sys` directly (CPU, GPU on Jetson, memory, disk, temperatures, power rails, fans)
- Shows the OS release, kernel, architecture and hostname (plus the L4T release on Jetson)
- Detects the platform (Jetson Orin / Xavier, Raspberry Pi, PC, Linux) and hides what the board lacks

## Usage

platmon runs as a background service on the device (see "Run at boot": systemd or Docker), and you look at
it with the `platmon` command, a browser, or `curl`:

```sh
platmon                          # this device: live view, Ctrl+C to quit
platmon 192.168.55.53            # another device (host[:port], default port 9797)
platmon 192.168.55.53 2          # update every 2 s
platmon --once                   # one snapshot without clearing the screen (scripts, ssh, logs)
```

If the service is not running, `platmon` says so and how to start it. On the device the command comes
with the service: `scripts/systemd/install.sh` puts it in `/usr/local/bin`, `scripts/docker/start.sh` in
`~/.local/bin` (no sudo), and both update it when run again. On a PC that only watches devices, install
just the command with `scripts/install-cli.sh` (or `--user`, no sudo); it is one standard-library Python
file (`frontends/cli.py`).

In a browser: `http://<host>:9797`. Without Python, from any machine with curl (Windows and macOS too):
`watch -n1 curl -s <host>:9797/text` shows the same screen as `platmon`. Raw data: `http://<host>:9797/api/stats`, collector state:
`http://<host>:9797/api/status` (fields and freshness rules: [docs/api.md](docs/api.md); per-interface
network counters: [docs/network.md](docs/network.md); disk I/O counters: [docs/disk-io.md](docs/disk-io.md); storage capacity, opt-in: [docs/storage.md](docs/storage.md)). The API has no
authentication. Run it on trusted networks only.

To run the server in the foreground instead (e.g. while developing):
`python3 platmon.py [platmon.ini]`. `platmon.ini` lists every option with its default (collection
interval, network and disk I/O counters on/off, HTTP bind/port, web page on/off).

### Layout

```
platmon.py   server: config -> one collector core -> HTTP API and web page
collector/   core: collect() (common.py for any Linux, jetson.py for Jetson) and the background Sampler
frontends/   server.py (HTTP + web/), cli.py (terminal client, installed as `platmon`)
scripts/     systemd/ and docker/ start/stop scripts, install-cli.sh
tests/
```

### Run at boot

Two ways: systemd or Docker. Both serve port 9797, so use one at a time; the scripts refuse to start
one way while the other is running (or, for systemd, still enabled at boot).

**systemd** (the scripts ask for sudo):

```sh
scripts/systemd/install.sh              # install or update (after git pull), enable at boot, start, add `platmon`
scripts/systemd/start.sh                # start, or restart to apply config changes; checks /api/stats
scripts/systemd/stop.sh                 # stop for now; still enabled, so it starts again at boot
scripts/systemd/uninstall.sh            # stop, disable, remove /opt/platmon, the unit and `platmon`; keeps the config
scripts/systemd/uninstall.sh --purge    # ... and remove /etc/platmon too
```

`install.sh` copies the code to `/opt/platmon` and the unit to `/etc/systemd/system/`. It creates
`/etc/platmon/platmon.ini` from `platmon.ini` only if that file does not exist yet, so your edits are
kept. It checks the config first and changes nothing if it is invalid. Logs: `journalctl -u platmon`.
The default port was 8080 before; an existing `/etc/platmon/platmon.ini` keeps its port, so edit it
(or `uninstall.sh --purge` and install again) to move to 9797. `start.sh` prints the port in use.

### Docker

No image is published: build it yourself on the device (see "Container image licensing" below).
`up` builds the image `platmon:local` from this checkout the first time; add `--build` after a `git pull`.
The container monitors the host, so it needs a few read-only host mounts (all set in `compose.yaml`):

```sh
scripts/docker/start.sh    # build and start; on Jetson adds compose.jetson.yaml (nvpmodel power mode); waits until healthy
scripts/docker/stop.sh     # stop and remove the container (the image stays)
```

`start.sh` also installs the `platmon` command in `~/.local/bin`; `stop.sh` leaves it, since it can watch other devices too
(`scripts/install-cli.sh --user --uninstall` removes it).

Without the scripts: `BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose up -d --build` (Jetson: add
`-f compose.yaml -f compose.jetson.yaml`). The variable keeps the image id stable when nothing changed;
without it some Docker versions give every build a new id, and the running container's image can be
deleted out from under it.

- `/sys/firmware` → board detection. Docker hides the device tree, so without this mount a Jetson
  shows up as "PC" and loses its GPU, power mode and fan data. The startup log line
  `platmon: platform …` shows what was detected.
- `/` (not recursive) → the host's root filesystem: disk usage, and the OS release (`/etc/os-release`)
  and L4T release so they show the host, not the image. The host's `/proc`, `/sys` and `/run` are not
  exposed through it.
- `./platmon.ini` → config. Keep `[http] port = 9797` inside the container and change the
  published port in `compose.yaml` instead (the health check uses 9797).
- Runs as an unprivileged user, needs no NVIDIA container runtime, and is marked unhealthy while
  `/api/stats` has no current data.

#### Container image licensing

platmon itself is Apache-2.0 and uses only the Python standard library. The image it builds on,
`python:3.13-slim`, is Debian-based and contains GPL/LGPL software (e.g. bash, coreutils, apt,
glibc), as any Linux base image does. So:

- This repository ships only the `Dockerfile` and compose files; it does **not** publish images.
  Building and running the image on your own machine is not distribution.
- If you push an image you built to a registry or hand it to others, you distribute those
  components and take on their license obligations (offering the corresponding source, keeping
  license notices). platmon stays Apache-2.0: it is only packaged alongside them, not linked into them.
- The image deliberately uses a plain Python base, not an NVIDIA L4T one, so it bundles no NVIDIA
  binaries; platmon reads `/proc` and `/sys` only.

This is a summary of the project's policy, not legal advice.

## Test

```sh
pip install pytest   # test-only; runtime stays dependency-free
pytest
```

## License

Apache-2.0

[Brand assets and colors](frontends/web/assets/brand/README.md)
