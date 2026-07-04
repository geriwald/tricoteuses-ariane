#!/usr/bin/env python3
"""B2 `ariane-replay` — HTTP layer: a perfect mock of the real AN endpoints.

B1 polls the same paths it would poll live; B2 answers with the raw bytes B3
captured, gated wall<=t, so B1 cannot tell replay from live (spec §B2). Only two
sources are causal here — derouleur and Eliasse (corrected 2026-07-01: the live NVS
is neither causal nor ground truth, it is ignored). Non-causal data (the frozen
referential, the ground-truth VOD NVS, the video) is served out of the clock.

`resolve_route` is the pure dispatch (status, content_type, body_bytes), tested
without a socket. The running server (clock, transport, video Range) builds on it.
"""
import json
from datetime import timedelta

# Real AN paths B1 polls live — B2 mirrors them so the mock is path-exact.
DEROULEUR_PATH = "/local/derouleur/derouleur.json"
ELIASSE_PROCHAIN_PATH = "/eliasse/prochainADiscuter.do"
ELIASSE_AMENDEMENT_PATH = "/eliasse/amendement.do"

JSON = "application/json"
XML = "text/xml"


def _reconstruct_prochain(summary):
    """Rebuild the real prochainADiscuter.do shape from the captured summary.
    Faithful on the fields B1 reads; organe → organeAbrv (real field name)."""
    return {"prochainADiscuter": {
        "bibard": summary.get("bibard"),
        "bibardSuffixe": summary.get("bibardSuffixe", ""),
        "numAmdt": summary.get("numAmdt"),
        "legislature": summary.get("legislature", "17"),
        "organeAbrv": summary.get("organe"),
    }}


def _reconstruct_amendement(summary):
    """Rebuild the real amendement.do shape from the captured summary. Only the
    fields B1 reads are present (sort→sortEnSeance, etat, place→placeReference,
    numAmdt→numero); author/dispositif were never captured (option A)."""
    return {"amendements": [{
        "numero": summary.get("numAmdt"),
        "sortEnSeance": summary.get("sort", ""),
        "etat": summary.get("etat"),
        "placeReference": summary.get("place"),
        "bibard": summary.get("bibard"),
        "organeAbrv": summary.get("organe"),
    }]}


def clock_state(clock):
    """The clock state the UI reads: current `t` and whether it is playing."""
    return {"t_ms": clock.t_ms(), "playing": clock.playing}


def clock_payload(clock, origin):
    """The /clock response: the state plus the sitting's video-start `origin` and the
    broadcast wall-clock (origin + t), so B4 can show the real date/time on air."""
    t_ms = clock.t_ms()
    return {
        "t_ms": t_ms,
        "playing": clock.playing,
        "origin": origin.isoformat(),
        "wall": (origin + timedelta(milliseconds=t_ms)).isoformat(),
    }


def apply_transport(clock, command, params):
    """Drive the MasterClock by a transport command (play/pause/seek/seek_by) and
    return its new state. The UI sends commands only, never a pushed `t` (spec §B2).
    `seek` takes `t` (ms), `seek_by` takes `delta` (ms)."""
    if command == "play":
        clock.play()
    elif command == "pause":
        clock.pause()
    elif command == "seek":
        clock.seek(int(params["t"]))
    elif command == "seek_by":
        clock.seek_by(int(params["delta"]))
    else:
        raise ValueError(f"unknown transport command: {command!r}")
    return clock_state(clock)


def resolve_route(record, t_ms, path):
    """Dispatch a GET to (status, content_type, body_bytes).

    Causal routes are gated wall<=t (a source not yet present → 404, exactly as the
    live would show nothing). Non-causal routes ignore `t`.
    """
    if path == DEROULEUR_PATH:
        body = record.raw_bytes("derouleur", t_ms)
        if body is None:
            return 404, JSON, b""
        return 200, JSON, body

    if path in (ELIASSE_PROCHAIN_PATH, ELIASSE_AMENDEMENT_PATH):
        # option B (new bundles): serve the captured .do body VERBATIM, gated wall<=t.
        source = ("eliasse_prochain" if path == ELIASSE_PROCHAIN_PATH
                  else "eliasse_amendement")
        body = record.raw_bytes(source, t_ms)
        if body is not None:
            return 200, JSON, body
        # option A (old bundles): fall back to reconstructing the .do from the summary.
        summary = record.eliasse_summary(t_ms)
        if summary is None:
            return 404, JSON, b""
        rebuilt = (_reconstruct_prochain(summary) if path == ELIASSE_PROCHAIN_PATH
                   else _reconstruct_amendement(summary))
        return 200, JSON, json.dumps(rebuilt, ensure_ascii=False).encode("utf-8")

    if path.startswith("/referential/") and path.endswith(".json"):
        name = path[len("/referential/"):-len(".json")]
        body = record.referential_bytes(name)
        if body is None:
            return 404, JSON, b""
        return 200, JSON, body

    if path == "/ground-truth/timeline":
        tl = record.nvs_timeline()
        if tl is None:
            return 404, JSON, b""
        return 200, JSON, json.dumps(tl, ensure_ascii=False).encode("utf-8")

    if path == "/ground-truth/tree":
        tree = record.nvs_tree()
        if tree is None:
            return 404, JSON, b""
        return 200, JSON, json.dumps(tree, ensure_ascii=False).encode("utf-8")

    if path.startswith("/ground-truth/"):
        body = record.ground_truth_bytes(path[len("/ground-truth/"):])
        if body is None:
            return 404, XML, b""
        return 200, XML, body

    return 404, JSON, b""


# ---- HTTP server -------------------------------------------------------------

import argparse
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import stream

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from ariane_env import load_dotenv

load_dotenv()
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _make_handler(state):
    """A request handler over the mutable server state:
    {"record": Record, "clock": MasterClock, "streamer": LiveStreamer,
     "records_dir": str} — mutable because B4 can switch the sitting."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # keep the console quiet; the demo has its own UI
            pass

        def _send(self, status, ctype, body, cache=True):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            if not cache:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(self, obj, status=200):
            self._send(status, JSON, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            path = urlparse(self.path).path
            record, clock = state["record"], state["clock"]

            if path == "/clock":
                return self._send_json(clock_payload(clock, record.origin))
            if path == "/video":
                return self._serve_video()
            if path.startswith("/live/"):
                # the record re-broadcast as a LIVE sliding HLS (the direct's shape)
                name = path[len("/live/"):]
                body = state["streamer"].file(name)
                if body is None:
                    return self._send(404, JSON, b"")
                ctype = stream.CONTENT_TYPES.get(os.path.splitext(name)[1], JSON)
                return self._send(200, ctype, body, cache=False)
            if path == "/records":
                cur = os.path.basename(record.path.rstrip("/"))
                return self._send_json(stream.list_records(state["records_dir"], cur))

            # everything else is a data route, gated on the live clock `t`
            status, ctype, body = resolve_route(record, clock.t_ms(), path)
            self._send(status, ctype, body)

        do_HEAD = do_GET

        def do_OPTIONS(self):
            # CORS preflight for the cross-origin POST /clock/* from B4 (other port)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def do_POST(self):
            u = urlparse(self.path)
            clock, streamer = state["clock"], state["streamer"]

            if u.path == "/record":
                return self._switch_record(parse_qs(u.query).get("name", [""])[0])

            m = re.fullmatch(r"/clock/(play|pause|seek|seek_by)", u.path)
            if not m:
                return self._send_json({"error": "not found"}, 404)
            try:
                st = apply_transport(clock, m.group(1),
                                     {k: v[0] for k, v in parse_qs(u.query).items()})
            except (KeyError, ValueError) as e:
                return self._send_json({"error": str(e)}, 400)
            # the live edge is the clock's slave: follow every transport move
            if clock.playing:
                streamer.start(clock.t_ms())
            else:
                streamer.stop()
            self._send_json(st)

        def _switch_record(self, name):
            """Load another sitting: new Record, clock reset to 0 (paused),
            streamer repointed. B1 keeps polling the same URLs and just sees
            the new sitting (restart B1 to reload actors/organes referentials)."""
            safe = stream.safe_record_name(name)
            if not safe:
                return self._send_json({"error": "bad record name"}, 400)
            path = os.path.join(state["records_dir"], safe)
            try:
                from replay import Record
                record = Record(path)
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            state["record"] = record
            state["clock"].pause()
            # skip the pre-sitting providéo: land where the speech starts
            # (one-shot detect_start.py data; 0 if never computed)
            state["clock"].seek(record.sitting_start_ms())
            state["streamer"].set_video(record.video_path())
            self._send_json({"name": safe, "origin": record.origin.isoformat(),
                             "sitting_start_ms": record.sitting_start_ms()})

        def _serve_video(self):
            """Serve the mp4 with HTTP Range so the <video> can seek (2 GB file).
            The video is the clock's slave — the UI sets currentTime to follow `t`;
            here we just serve bytes, honouring Range."""
            path = state["record"].video_path()
            size = os.path.getsize(path)
            rng = self.headers.get("Range")
            m = _RANGE.match(rng or "")
            if not m:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                if self.command != "HEAD":
                    with open(path, "rb") as f:
                        self._pipe(f, 0, size - 1)
                return
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if self.command != "HEAD":
                with open(path, "rb") as f:
                    self._pipe(f, start, end)

        def _pipe(self, f, start, end):
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client hung up mid-stream (ffmpeg probing/seeking does this)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="B2 ariane-replay — causal replayer")
    ap.add_argument("--record", default=os.environ.get("ARIANE_RECORD", ""),
                    help="capture bundle to replay (a record/ dir produced by b3-capture)")
    ap.add_argument("--records-dir", default=None,
                    help="directory of capture bundles for the B4 picker "
                         "(default: the --record's parent)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="127.0.0.1",
                    help="bind address (0.0.0.0 to serve B4 across Tailscale)")
    args = ap.parse_args()

    from replay import Record, MasterClock
    record = Record(args.record)
    clock = MasterClock()
    clock.seek(record.sitting_start_ms())  # land where the speech starts
    state = {
        "record": record,
        "clock": clock,
        "streamer": stream.LiveStreamer(record.video_path()),
        "records_dir": args.records_dir or os.path.dirname(args.record.rstrip("/")),
    }
    handler = _make_handler(state)
    httpd = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"B2 ariane-replay on http://{args.bind}:{args.port}  "
          f"(record: {args.record}, origin t=0 at {record.origin.isoformat()})")
    print("  POST /clock/play|pause|seek?t=..|seek_by?delta=..  POST /record?name=..")
    print("  GET /clock  /live/stream.m3u8  /records  /video")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
