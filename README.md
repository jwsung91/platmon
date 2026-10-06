# platmon

Lightweight platform monitor for Jetson, Raspberry Pi, PCs and other Linux hosts.
One collector core runs on the device; the frontends enabled in its config (HTTP API + web page, terminal) show what it collects.

- No dependencies: Python 3.9+ standard library only
- Reads `/proc` and `/sys` directly (CPU, GPU on Jetson, memory, disk, temperatures, power rails, fans)
- Detects the platform (Jetson Orin / Xavier, Raspberry Pi, PC, Linux) and hides what the board lacks

## Usage

On the device:

```sh
python3 platmon.py [platmon.ini]             # defaults: HTTP API + web page on :8080
python3 platmon.py --frontends terminal      # draw in this terminal, no server
python3 platmon.py --frontends http,terminal
```

`platmon.ini` lists every option with its default (collection interval, HTTP bind/port, web page on/off,
which frontends run). `--frontends` overrides the `enabled` settings.

From anywhere on the network, open `http://<host>:8080` in a browser, or use the remote terminal client
(`frontends/cli.py` needs nothing else, copy it anywhere):

```sh
python3 frontends/cli.py <host>[:port] [interval]
```

Raw data: `http://<host>:8080/api/stats`. The API has no authentication. Run it on trusted networks only.

### Layout

```
platmon.py   launcher: config -> one collector core -> enabled frontends
collector/   core: collect() (common.py for any Linux, jetson.py for Jetson) and the background Sampler
frontends/   server.py (HTTP + web/), terminal.py, cli.py (remote client)
tests/
```

### Run at boot

Two ways: systemd or Docker. Both serve port 8080, so use one at a time; the scripts refuse to start
one way while the other is running (or, for systemd, still enabled at boot).

**systemd** (the scripts ask for sudo):

```sh
scripts/systemd/install.sh              # install or update (after git pull), enable at boot, start
scripts/systemd/start.sh                # start, or restart to apply config changes; checks /api/stats
scripts/systemd/stop.sh                 # stop for now; still enabled, so it starts again at boot
scripts/systemd/uninstall.sh            # stop, disable, remove /opt/platmon and the unit; keeps the config
scripts/systemd/uninstall.sh --purge    # ... and remove /etc/platmon too
```

`install.sh` copies the code to `/opt/platmon` and the unit to `/etc/systemd/system/`. It creates
`/etc/platmon/platmon.ini` from `platmon.ini` only if that file does not exist yet, so your edits are
kept. It checks the config first and changes nothing if it is invalid. Logs: `journalctl -u platmon`.

### Docker

No image is published: build it yourself on the device (see "Container image licensing" below).
`up` builds the image `platmon:local` from this checkout the first time; add `--build` after a `git pull`.
The container monitors the host, so it needs a few read-only host mounts (all set in `compose.yaml`):

```sh
scripts/docker/start.sh    # build and start; on Jetson adds compose.jetson.yaml (nvpmodel power mode); waits until healthy
scripts/docker/stop.sh     # stop and remove the container (the image stays)
```

Without the scripts: `docker compose up -d --build` (Jetson: `docker compose -f compose.yaml -f compose.jetson.yaml up -d --build`).

- `/sys/firmware` → board detection. Docker hides the device tree, so without this mount a Jetson
  shows up as "PC" and loses its GPU, power mode and fan data. The startup log line
  `platmon: platform …` shows what was detected.
- `/` (not recursive) → disk usage of the host's root filesystem. The host's `/proc`, `/sys` and
  `/run` are not exposed through it.
- `./platmon.ini` → config. Keep `[http] port = 8080` inside the container and change the
  published port in `compose.yaml` instead (the health check uses 8080).
- Runs as an unprivileged user, needs no NVIDIA container runtime, and is marked unhealthy while
  `/api/stats` has no current data. The terminal frontend needs a TTY:
  `docker compose run --rm platmon --frontends terminal`.

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
