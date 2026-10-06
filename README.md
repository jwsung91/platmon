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

or open `http://<host>:8080` in a browser. Raw data: `http://<host>:8080/api/stats`.

The API has no authentication. Run it on trusted networks only.

### Run at boot (systemd)

```sh
sudo mkdir -p /opt/platmon/web
sudo cp server.py /opt/platmon/ && sudo cp web/index.html /opt/platmon/web/
sudo cp platmon.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now platmon
```

## Test

```sh
python3 test_server.py
```

## License

Apache-2.0
