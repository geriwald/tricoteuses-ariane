#!/usr/bin/env python3
"""Relecture causale HORS-LIGNE pour la démo B4 (aucun GPU, aucun réseau).

Rejoue les segments STT réels d'une séance (stt-offline-*.ndjson) dans les cœurs
PURS de B1 (weaver.Weaver + deduce.Deducer) avec les vrais référentiels
(acteurs/organes/derouleur), produit le fil `thread.ndjson`, puis :
  - sert  GET /thread     en SSE (backlog complet, comme B1 :8100),
  - sert  GET /video.mp4  en Range (la VOD, pour un rendu vidéo synchronisé).

Usage :
  python demo_replay.py --bundle <data/2026-06-26-evening> [--port 8100] [--serve]
  python demo_replay.py --bundle ... --generate-only   # écrit thread.ndjson et résume
"""
import argparse
import glob
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

B1 = os.path.join(os.path.dirname(__file__), "..")  # remplacé par --b1 si besoin


def load_json(path):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _pick_video(bundle):
    """La vidéo à scanner/servir : on préfère le stream-copy faststart aligné
    (petit, mêmes timecodes) au raw hémicycle (multi-Go)."""
    vids = glob.glob(os.path.join(bundle, "video", "*.mp4"))
    if not vids:
        return None
    vids.sort(key=lambda p: (0 if "faststart" in os.path.basename(p).lower()
                             or "demo" in os.path.basename(p).lower() else 1,
                             os.path.getsize(p)))
    return vids[0]


def scan_ocr_events(bundle, b1_dir, step_s=3.0, end_s=None, lang="fra",
                    tesseract=None, ffmpeg="ffmpeg"):
    """Scanne la vidéo du bundle pour les écrans-résultat de scrutin (spike OCR) et
    rend la liste des events `scrutin_result` (triés par t_ms).

    Même axe temporel que le STT offline : les timecodes t_s sortent en secondes
    de contenu, donc t_ms s'interleave directement avec les `beg` des segments."""
    spike = os.path.join(b1_dir, "..", "spikes", "2026-07-03-scrutin-ocr")
    spike = os.path.abspath(spike)
    if spike not in sys.path:
        sys.path.insert(0, spike)
    import scrutin_ocr
    scrutin_ocr._resolve_tesseract(tesseract)
    video = _pick_video(bundle)
    if not video:
        print("[ocr] aucune vidéo dans le bundle — scan ignoré", file=sys.stderr)
        return []
    try:
        # ne jamais chercher AU-DELÀ de la dernière frame : ffmpeg -ss échoue et
        # scan_video (check=True) perdrait tout le scan sur cette seule frame
        duration = scrutin_ocr._ffprobe_duration(video, ffmpeg)
        if end_s is None or end_s > duration:
            end_s = max(0.0, duration - step_s)  # never past the last frame, never negative
        bound = f", jusqu'à {end_s:.0f}s" if end_s else ""
        print(f"[ocr] scan {os.path.basename(video)} (pas {step_s:g}s{bound}) …",
              file=sys.stderr)
        events = scrutin_ocr.scan_video(video, step_s=step_s, end_s=end_s, lang=lang,
                                        ffmpeg=ffmpeg)
    except Exception as e:  # scan raté : le fil se génère sans chiffré (dégradation propre)
        print(f"[ocr] scan échoué ({e}) — thread généré sans chiffré", file=sys.stderr)
        return []
    events.sort(key=lambda e: e["t_ms"])
    for e in events:
        print(f"[ocr]   t={e['t_ms']/1000:7.1f}s  POUR={e['pour']} CONTRE={e['contre']}"
              f" votants={e['votants']} maj={e['majorite']}  ok={e['ok']} conf={e['confidence']}",
              file=sys.stderr)
    return events


def build_thread(bundle, b1_dir, ocr=None, ocr_events_file=None):
    sys.path.insert(0, b1_dir)
    import weaver as w
    import deduce

    actors = load_json(os.path.join(bundle, "referential", "acteurs.json"))
    organes = load_json(os.path.join(bundle, "referential", "organes.json"))
    amendments = load_json(os.path.join(bundle, "referential", "amendements.json"))

    agenda = deduce.AgendaIndex()
    snaps = sorted(glob.glob(os.path.join(bundle, "raw", "derouleur", "*.json")))
    folded = 0
    for p in snaps:
        try:
            agenda.update(load_json(p))
            folded += 1
        except Exception:
            pass

    seq = w.Seq()
    weaver = w.Weaver(seq=seq)
    deducer = deduce.Deducer(agenda, actors, organes, seq=seq, amendments=amendments)

    stt = glob.glob(os.path.join(bundle, "stt-offline-*.ndjson"))
    if not stt:
        raise SystemExit(f"pas de stt-offline-*.ndjson dans {bundle}")
    segs = []
    with open(stt[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segs.append(json.loads(line))

    # OCR (optionnel) : les écrans-résultat, à interleaver par timecode avec le STT
    # pour que chaque chiffré s'attache à l'amendement courant (deducer._current)
    ocr_events = []
    if ocr_events_file:  # events déjà scannés (scrutin_result NDJSON) — pas de re-scan
        with open(ocr_events_file, encoding="utf-8") as f:
            ocr_events = [json.loads(line) for line in f if line.strip()]
        ocr_events.sort(key=lambda e: e["t_ms"])
        print(f"[ocr] {len(ocr_events)} event(s) chargés de {ocr_events_file}", file=sys.stderr)
    elif ocr:
        cfg = dict(ocr)
        override_end = cfg.pop("end_s", None)  # --ocr-end : borne le scan (plus rapide)
        end_s = override_end if override_end is not None else (
            (max((s.get("end") or s["beg"]) for s in segs) + 30) if segs else None)
        ocr_events = scan_ocr_events(bundle, b1_dir, end_s=end_s, **cfg)

    nodes = []
    oi = 0
    for seg in segs:
        beg_ms = seg["beg"] * 1000
        while oi < len(ocr_events) and ocr_events[oi]["t_ms"] <= beg_ms:
            for extra in deducer.feed_scrutin_result(ocr_events[oi]):  # ballot chiffré (ocr)
                nodes.append(extra)
            oi += 1
        ev = {"type": "utterance", "beg": seg["beg"],
              "end": seg.get("end"), "text": seg["text"]}
        for node in weaver.feed(ev):        # -> le nœud utterance
            nodes.append(node)
            for extra in deducer.feed(node):  # -> amendment/speaker/ballot déduits
                nodes.append(extra)
    while oi < len(ocr_events):              # écrans-résultat après la dernière parole
        for extra in deducer.feed_scrutin_result(ocr_events[oi]):
            nodes.append(extra)
        oi += 1

    print(f"[build] {os.path.basename(stt[0])} : {len(nodes)} nœuds "
          f"({folded}/{len(snaps)} snapshots dérouleur, {len(actors)} acteurs, "
          f"{len(ocr_events)} scrutin(s) OCR)", file=sys.stderr)
    kinds = {}
    for n in nodes:
        if n["kind"] != "utterance":
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    print(f"[build] déduits : {kinds}", file=sys.stderr)
    return nodes


def summarize(nodes):
    print("\n--- nœuds déduits (t en s) ---", file=sys.stderr)
    for n in nodes:
        if n["kind"] == "utterance":
            continue
        c = n.get("canonical", {})
        extra = ""
        if n["kind"] == "speaker":
            extra = f" call={n.get('call')} grp={n.get('groupe_label')}"
        if c.get("amendement_uid"):
            extra += f" uid=…{c['amendement_uid'][-8:]}"
        print(f"  {n['t']/1000:7.1f}  {n['kind']:9} {n['text']!r}{extra}", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    nodes = []
    video_path = None

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_GET(self):
        if self.path.startswith("/thread.json"):
            return self._thread_json()
        if self.path.startswith("/thread"):
            return self._thread()
        if self.path.startswith("/video"):
            return self._video()
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def _thread_json(self):
        """Tout le fil en une réponse JSON qui SE TERMINE (réseau au repos -> capture)."""
        body = json.dumps(self.nodes, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _thread(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        try:
            for n in self.nodes:  # tout le backlog d'un coup (le front dédoublonne par seq)
                self.wfile.write(("data: " + json.dumps(n, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
            while True:           # garder la connexion ouverte (heartbeat SSE)
                time.sleep(15)
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _video(self):
        path = self.video_path
        if not path or not os.path.exists(path):
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
            return
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            start = int(s) if s else 0
            end = int(e) if e else size - 1
            end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self._cors()
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    buf = f.read(min(1 << 20, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--b1", default=None, help="dir de b1-weaver (défaut: ../b1-weaver relatif au bundle repo)")
    ap.add_argument("--out", default=None, help="où écrire thread.ndjson")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--generate-only", action="store_true")
    ap.add_argument("--ocr", action="store_true", default=False,
                    help="scanner la vidéo du bundle (spike OCR) et tisser les ballots "
                         "chiffrés (votants/exprimés/majorité/POUR/CONTRE)")
    ap.add_argument("--ocr-step", type=float, default=3.0,
                    help="pas d'échantillonnage OCR en secondes (l'écran reste ~3-4s)")
    ap.add_argument("--ocr-end", type=float, default=None,
                    help="borner le scan OCR à N secondes (défaut: toute la durée du STT)")
    ap.add_argument("--ocr-lang", default="fra", help="langue tesseract")
    ap.add_argument("--ocr-events", default=None,
                    help="charger des events scrutin_result déjà scannés (NDJSON) au lieu "
                         "de re-scanner la vidéo — régénération rapide")
    ap.add_argument("--tesseract", default=None, help="chemin de l'exe tesseract")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="chemin de l'exe ffmpeg")
    ap.add_argument("--thread-file", default=None,
                    help="servir un thread.ndjson déjà généré sans reconstruire "
                         "(redémarrage instantané, pas de re-scan OCR)")
    args = ap.parse_args()

    if args.thread_file:  # servir tel quel : ni build ni re-scan
        with open(args.thread_file, encoding="utf-8") as f:
            nodes = [json.loads(line) for line in f if line.strip()]
        print(f"[load] {args.thread_file} : {len(nodes)} nœuds", file=sys.stderr)
    else:
        b1_dir = args.b1 or os.path.join(args.bundle, "..", "..", "b1-weaver")
        b1_dir = os.path.abspath(b1_dir)
        ocr = ({"step_s": args.ocr_step, "lang": args.ocr_lang, "end_s": args.ocr_end,
                "tesseract": args.tesseract, "ffmpeg": args.ffmpeg} if args.ocr else None)
        nodes = build_thread(os.path.abspath(args.bundle), b1_dir, ocr=ocr,
                             ocr_events_file=args.ocr_events)
        summarize(nodes)
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "thread.ndjson")
        with open(out, "w", encoding="utf-8") as f:
            for n in nodes:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        print(f"[out] {out}", file=sys.stderr)

    if args.generate_only:
        return

    Handler.nodes = nodes
    # serve the SAME video OCR scanned (faststart copy), so overlay timecodes align
    Handler.video_path = _pick_video(os.path.abspath(args.bundle))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[serve] SSE http://127.0.0.1:{args.port}/thread  "
          f"video={'/video.mp4' if Handler.video_path else '—'}", file=sys.stderr)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
