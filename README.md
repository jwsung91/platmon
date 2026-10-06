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

### Run at boot (systemd)

```sh
sudo mkdir -p /opt/platmon /etc/platmon
sudo cp -r platmon.py collector frontends /opt/platmon/
sudo cp platmon.ini /etc/platmon/
sudo cp platmon.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now platmon
```

### Docker

The container monitors the host, so it needs a few read-only host mounts (all set in `compose.yaml`):

```sh
docker compose up -d                                          # any Linux host
docker compose -f compose.yaml -f compose.jetson.yaml up -d   # Jetson: adds the nvpmodel power mode
```

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

Only the Dockerfile ships here; no image is published.

## Test

```sh
pip install pytest   # test-only; runtime stays dependency-free
pytest
```

## License

Apache-2.0
