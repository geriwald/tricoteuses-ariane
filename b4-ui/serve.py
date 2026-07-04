#!/usr/bin/env python3
"""B4 ariane-ui — static server for the live UI, plus proxy for demo-replay.

Serves demo.html on :8080. Proxies the following to demo_replay (default :8100):
  GET /thread          — SSE event stream
  GET /thread.json     — full thread dump
  GET /video.mp4       — Range-served video
Also exposes:
  GET /start-epoch?id=<direct-id>  — liveplayer.nvs anchor proxy

Usage:
  python3 serve.py --port 8080   ->  open http://127.0.0.1:8080/demo.html
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

NVS_URL = "https://videos.assemblee-nationale.fr/Datas/an/{did}/content/liveplayer.nvs"
_STARTTIME = re.compile(rb'starttime="(\d+)"')

PROXY_PATHS = {"/thread", "/thread.json", "/video.mp4"}


class Handler(SimpleHTTPRequestHandler):
    backend_host = "127.0.0.1"
    backend_port = "8100"

    @property
    def backend_url(self):
        return f"http://{self.backend_host}:{self.backend_port}"

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/start-epoch":
            return self._start_epoch(parse_qs(u.query).get("id", [""])[0])
        if u.path in PROXY_PATHS:
            return self._proxy_to(u.path)
        return super().do_GET()

    def _proxy_to(self, backend_path):
        """Proxy GET to demo_replay, streaming the response (SSE / video / JSON)."""
        backend_url = f"http://{self.backend_host}:{self.backend_port}{backend_path}"
        try:
            req = urllib.request.Request(backend_url)
            for header in ("Range", "If-Modified-Since", "If-None-Match"):
                val = self.headers.get(header)
                if val:
                    req.add_header(header, val)
            resp = urllib.request.urlopen(req, timeout=None)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            return
        except urllib.error.URLError:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"backend unreachable"}')
            return

        self.send_response(resp.status)
        skip = {"transfer-encoding", "content-encoding", "connection"}
        for key, val in resp.headers.items():
            if key.lower() not in skip:
                self.send_header(key, val)
        if resp.headers.get("Content-Length"):
            self.send_header("Content-Length", resp.headers["Content-Length"])
        self.end_headers()

        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _start_epoch(self, did):
        """Fetch liveplayer.nvs for `did`, return {start_epoch} — server-side, no CORS."""
        did = did.strip()
        try:
            req = urllib.request.Request(NVS_URL.format(did=did),
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read()
            m = _STARTTIME.search(body)
            if not m:
                return self._json({"error": "no starttime in liveplayer.nvs"}, 502)
            self._json({"start_epoch": int(m.group(1)), "id": did})
        except Exception as e:
            self._json({"error": str(e)}, 502)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--backend-host", default=Handler.backend_host,
                    help="demo_replay host (default: 127.0.0.1)")
    ap.add_argument("--backend-port", default=Handler.backend_port,
                    help="demo_replay port (default: 8100)")
    args = ap.parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    Handler.backend_host = args.backend_host
    Handler.backend_port = args.backend_port
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"B4 ariane-ui on http://0.0.0.0:{args.port}  "
          f"(backend: {Handler.backend_host}:{Handler.backend_port}"
          f", proxy: /thread /video.mp4 /start-epoch)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
