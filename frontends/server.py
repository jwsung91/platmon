"""HTTP frontend: JSON at /api/stats, the sampler's runtime status at /api/status, the terminal view as plain
text at /text (for curl and watch) and, when web is enabled, the web viewer at /. Started by platmon.py.
Contract: docs/api.md."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cli import render

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
BRAND_ASSETS = {
    "/assets/brand/platmon-logo-light.svg": "platmon-logo-light.svg",
    "/assets/brand/platmon-logo-dark.svg": "platmon-logo-dark.svg",
    "/assets/brand/favicon.svg": "favicon.svg",
}
LIVE = ("/api/stats", "/api/status", "/text")


def make_handler(sampler, web=True):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/status":  # never waits for the first snapshot; 200 even when not ready
                body, ctype = json.dumps(sampler.read()[1]).encode(), "application/json"
            elif self.path in ("/api/stats", "/text"):
                # code and body from the same capture; /api/stats serializes the snapshot without copying it
                if self.path == "/api/stats":
                    stats, status = sampler._stats_json(timeout=5.0)
                else:
                    stats, status = sampler.read(timeout=5.0)
                if stats is None:  # JSON for the API, text for /text, so clients need not parse an HTML page
                    why = "no current data (not collected yet, or collection keeps failing)"
                    if self.path == "/api/stats":  # the last good sample's identity and age, never its values
                        body = {"error": why, "schema_version": status["schema_version"], "code": "no_current_data",
                                "instance_id": status["instance_id"], "sample": status["sample"]}
                        self.reply(503, json.dumps(body).encode(), "application/json")
                    else:
                        self.reply(503, (why + "\n").encode(), "text/plain; charset=utf-8")
                    return
                if self.path == "/api/stats":
                    body, ctype = stats, "application/json"  # already the JSON bytes
                else:  # same screen as the platmon command: watch -n1 curl -s host:9797/text
                    body, ctype = (render(stats) + "\n").encode(), "text/plain; charset=utf-8"
            elif web and self.path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    body, ctype = f.read(), "text/html; charset=utf-8"
            elif web and self.path in BRAND_ASSETS:
                with open(os.path.join(WEB_DIR, "assets", "brand", BRAND_ASSETS[self.path]), "rb") as f:
                    body, ctype = f.read(), "image/svg+xml"
            else:
                self.send_error(404)
                return
            self.reply(200, body, ctype)

        def reply(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if self.path in LIVE:  # a cached answer would show old data as current
                self.send_header("Cache-Control", "no-store")
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
