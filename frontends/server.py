"""HTTP frontend: JSON at /api/stats, the terminal view as plain text at /text (for curl and watch) and,
when web is enabled, the web viewer at /. Started by platmon.py."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cli import render

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def make_handler(sampler, web=True):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/api/stats", "/text"):
                stats = sampler.latest()
                if stats is None:  # JSON for the API, text for /text, so clients need not parse an HTML page
                    why = "no current data (not collected yet, or collection keeps failing)"
                    if self.path == "/api/stats":
                        self.reply(503, json.dumps({"error": why}).encode(), "application/json")
                    else:
                        self.reply(503, (why + "\n").encode(), "text/plain; charset=utf-8")
                    return
                if self.path == "/api/stats":
                    body, ctype = json.dumps(stats).encode(), "application/json"
                else:  # same screen as the platmon command: watch -n1 curl -s host:9797/text
                    body, ctype = (render(stats) + "\n").encode(), "text/plain; charset=utf-8"
            elif web and self.path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    body, ctype = f.read(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.reply(200, body, ctype)

        def reply(self, code, body, ctype):
            self.send_response(code)
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
