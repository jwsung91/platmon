"""HTTP frontend: JSON at /api/stats and, when web is enabled, the web viewer at /. Started by platmon.py."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def make_handler(sampler, web=True):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/stats":
                stats = sampler.latest()
                if stats is None:
                    self.send_error(503, "no current data (not collected yet, or collection keeps failing)")
                    return
                body, ctype = json.dumps(stats).encode(), "application/json"
            elif web and self.path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    body, ctype = f.read(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def start(sampler, cfg):
    """cfg: the [http] config section (bind, port, web)."""
    httpd = ThreadingHTTPServer((cfg.get("bind"), cfg.getint("port")), make_handler(sampler, cfg.getboolean("web")))
    print(f"platmon http on {cfg.get('bind')}:{cfg.getint('port')}", flush=True)
    t = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    t.start()
    return t
