# platmon

Lightweight platform monitor for Jetson, Raspberry Pi, PCs and other Linux hosts.
One collector serves a JSON API; a web page and a terminal viewer read it independently.

- No dependencies: Python 3.9+ standard library only
- Reads `/proc` and `/sys` directly (CPU, GPU on Jetson, memory, disk, temperatures, power rails, fans)
- Detects the platform (Jetson Orin / Xavier, Raspberry Pi, PC, Linux) and hides what the board lacks

## Usage

On the device:

```sh
python3 server.py [port]        # default 8080
```

Then from anywhere on the network:

```sh
python3 cli.py <host>[:port] [interval]   # terminal viewer
```

or open `http://<host>:8080` in a browser. On the device itself, `python3 cli.py --local` works without the server. Raw data: `http://<host>:8080/api/stats`.

The API has no authentication. Run it on trusted networks only.

### Run at boot (systemd)

```sh
sudo mkdir -p /opt/platmon
sudo cp -r server.py collector web /opt/platmon/
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
