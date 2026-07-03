#!/usr/bin/env python3
"""B4 ariane-ui — static server for the live UI, plus a tiny anchor proxy.

Serves index.html on :8080. Also exposes:
  GET /start-epoch?id=<direct-id>
which fetches the sitting's liveplayer.nvs server-side (the AN endpoint sends no
CORS header, so the browser can't read it) and returns its `starttime` epoch —
the video's start date, used by the UI to measure offsets.

  python3 serve.py --port 8080   ->  open http://127.0.0.1:8080
"""
import argparse
import json
import os
import re
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

NVS_URL = "https://videos.assemblee-nationale.fr/Datas/an/{did}/content/liveplayer.nvs"
_STARTTIME = re.compile(rb'starttime="(\d+)"')


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/start-epoch":
            return self._start_epoch(parse_qs(u.query).get("id", [""])[0])
        return super().do_GET()

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
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"B4 ariane-ui on http://127.0.0.1:{args.port}  (proxy: /start-epoch?id=<direct-id>)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
