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

## Test

```sh
pip install pytest   # test-only; runtime stays dependency-free
pytest
```

## License

Apache-2.0
