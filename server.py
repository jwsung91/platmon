#!/usr/bin/env python3
"""platmon HTTP server (Jetson, Raspberry Pi, PC, Linux). Serves JSON at /api/stats and the web viewer at /.

Usage: python3 server.py [port]   (default 8080)
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from collector import collect

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            body, ctype = json.dumps(collect()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
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


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"platmon on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
