"""B1 ariane-weaver — the live wiring (GPU + I/O side, kept out of the pure core).

Pipeline (spec 2026-07-01, D1/D2): a video URL -> ffmpeg extracts its audio track
(-vn) as PCM 16 kHz mono -> whisper_streaming (LocalAgreement) emits interim +
confirmed utterances -> the pure Weaver stamps them into thread.ndjson nodes ->
ThreadLog persists and Broadcaster fans them out over SSE.

B1 only ever knows a video URL (--source); it cannot tell replay (B2 /video) from
live (Vodalys HLS). That invariance is the whole point of the spec.

The thread is DEDUCED FROM SPEECH — never read from the régie's hand-keyed flows
(derouleur highlight, live NVS): Ariane replaces the régie, it does not parrot it.
Public lists (derouleur agenda, acteurs.json, Eliasse) only serve as lookup
referentials to resolve what was *heard* into canonical ids: with --agenda and
--actors, each confirmed utterance runs through the Deducer, which weaves the
amendment/speaker/ballot nodes it can deduce (spec 2026-07-02, speech-deduced).

This module is not unit-tested: it depends on the GPU model and a real stream. It
is validated by a real run against the running B2. The pure cores it drives
(weaver.py, deduce.py) are the tested part.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import deduce
import diar
import weaver as w

# the proven streaming stack (torch cu128 + faster-whisper): whisper_streaming's
# LocalAgreement policy, reused as-is. Point WHISPER_STREAMING_PATH at your clone
# of https://github.com/ufal/whisper_streaming (default assumes it sits next to
# this repo under ~/code/whisper-live/whisper_streaming).
_default_ws = os.path.expanduser("~/code/whisper-live/whisper_streaming")
sys.path.insert(0, os.environ.get("WHISPER_STREAMING_PATH", _default_ws))

SR = 16000


def audio_frames(source, min_chunk=1.0, user_agent=None, referer=None):
    """Yield PCM float32 chunks from any video URL/file, via ffmpeg (-vn: audio only).

    On a live HLS playlist ffmpeg tracks the live edge by default (-live_start_index
    -3): B1 reads the present, ~30 s behind, not the DVR history. user_agent/referer
    are the HTTP headers some CDNs (Vodalys/AN) require to serve the segments."""
    headers = []
    if user_agent:
        headers += ["-user_agent", user_agent]
    if referer:
        headers += ["-referer", referer]
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *headers, "-i", source,
         "-vn", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"],
        stdout=subprocess.PIPE,
    )
    chunk_bytes = int(SR * min_chunk) * 2
    try:
        while True:
            raw = ff.stdout.read(chunk_bytes)
            if not raw:
                break
            yield np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        ff.terminate()


def transcribe(source, weaver, emit_node, model="large-v3", compute_type="float16",
               user_agent=None, referer=None, vad=True, diar_worker=None,
               follow=False):
    """Drive Whisper over the source's audio, weaving every event into the thread."""
    from whisper_online import FasterWhisperASR, OnlineASRProcessor

    class ASR(FasterWhisperASR):
        # whisper_streaming hardcodes float16; on the shared 8GB GPU (desktop,
        # ComfyUI, browser) int8_float16 (~1.5GB) is the fit — same knob as
        # transcribe_vod.py, without touching the submodule
        def load_model(self, modelsize, cache_dir, model_dir):
            from faster_whisper import WhisperModel
            return WhisperModel(modelsize, device="cuda", compute_type=compute_type,
                                download_root=cache_dir)

    print(f"[load] faster-whisper {model} on cuda/{compute_type} (vad={vad}) ...",
          file=sys.stderr, flush=True)
    asr = ASR("fr", model)
    if vad:
        # silero VAD filter: drop non-speech before transcription, so silence
        # (suspensions, between speakers) produces nothing instead of hallucinations
        # ("Sous-titrage FR", "Merci"...). This is the STT "s'envoie en l'air" fix.
        asr.use_vad()
    online = OnlineASRProcessor(asr)
    print("[ready] streaming\n", file=sys.stderr, flush=True)

    def emit(event):
        for node in weaver.feed(event):
            emit_node(node)

    last_interim = ""
    while True:
        for audio in audio_frames(source, user_agent=user_agent, referer=referer):
            if diar_worker:
                diar_worker.push(audio)  # tee: same PCM, same time axis
            online.insert_audio_chunk(audio)

            cbeg, cend, ctext = online.process_iter()  # confirmed (LocalAgreement)
            if ctext:
                emit({"type": "utterance", "beg": cbeg, "end": cend, "text": ctext})
                print(f"✓ [{cbeg:6.1f}-{cend:6.1f}] {ctext}", file=sys.stderr, flush=True)
                last_interim = ""

            ibeg, iend, itext = online.to_flush(online.transcript_buffer.complete())
            itext = (itext or "").strip()
            if itext and itext != last_interim:
                emit({"type": "interim", "beg": ibeg or 0.0, "text": itext})
                last_interim = itext

        if not follow:
            break
        # a live source dried up (B2 playlist reset on pause/seek, network blip):
        # reconnect to the edge instead of dying. Timecodes stay on the flow
        # axis; the gap while disconnected simply never produces nodes.
        print("[stream] source ended — reconnecting in 2s", file=sys.stderr, flush=True)
        time.sleep(2)

    fbeg, fend, ftext = online.finish()
    if ftext:
        emit({"type": "utterance", "beg": fbeg, "end": fend, "text": ftext})


def _fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def poll_referentials(agenda_url, actors_url, organes_url, agenda, deducer,
                      interval=30.0):
    """Keep every lookup dictionary fresh — agenda, actors, organes.

    Sittings follow one another on the same live flow (and B4 can switch B2's
    record), so referentials are POLLED, never a restart reason. The agenda
    accumulates (the derouleur purges discussed lines); actors/organes are
    swapped whole. Errors skip the tick; only transitions are logged."""
    failing = False
    while True:
        try:
            agenda.update(_fetch_json(agenda_url))
            if actors_url:
                actors = _fetch_json(actors_url)
                organes = _fetch_json(organes_url) if organes_url else []
                deducer.set_referentials(actors, organes)
            if failing:
                print("[referentials] back up", file=sys.stderr, flush=True)
                failing = False
        except Exception as e:
            if not failing:
                print(f"[referentials] fetch failed ({e}), retrying every {interval}s",
                      file=sys.stderr, flush=True)
                failing = True
        time.sleep(interval)


class DiarWorker:
    """Anonymous speaker-boundary diarization on CPU (pyannote segmentation-3.0).

    Receives the same PCM chunks as Whisper (tee in the transcribe loop), keeps
    a sliding 10s window, infers every ~2s of new audio (~45ms CPU), and weaves
    a provisional anonymous speaker node at each detected turn boundary. The
    boundary says WHERE the turn changes; the name deduction says WHO — never
    guessed here (spec invariant, kept anonymous by design)."""

    WINDOW_S = 10.0
    HOP_S = 2.0

    def __init__(self, emit_node, seq):
        self._emit = emit_node
        self._seq = seq
        self._q = queue.Queue()
        self._detector = diar.BoundaryDetector()

    def push(self, chunk):
        self._q.put(chunk)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import torch
        from pyannote.audio import Model
        from pyannote.audio.utils.powerset import Powerset
        model = Model.from_pretrained("pyannote/segmentation-3.0")
        model.eval()
        ps = Powerset(3, 2)
        print("[diar] segmentation-3.0 loaded (CPU)", file=sys.stderr, flush=True)

        buf = np.zeros(0, dtype=np.float32)
        total_s = 0.0     # flow seconds consumed — Whisper's own time axis
        since_hop = 0.0
        max_len = int(self.WINDOW_S * SR)
        while True:
            chunk = self._q.get()
            buf = np.concatenate([buf, chunk])[-max_len:]
            total_s += len(chunk) / SR
            since_hop += len(chunk) / SR
            if since_hop < self.HOP_S or len(buf) < max_len:
                continue
            since_hop = 0.0
            x = torch.from_numpy(buf).reshape(1, 1, -1)
            with torch.no_grad():
                acts = ps.to_multilabel(model(x))[0].numpy()
            t = self._detector.feed_window(acts, total_s - self.WINDOW_S, self.WINDOW_S)
            if t is not None:
                self._emit({"t": int(t * 1000), "seq": self._seq.next(),
                            "kind": "speaker", "state": "provisional",
                            "text": "(nouvelle voix)",
                            "canonical": dict(deduce.EMPTY_CANONICAL),
                            "source": "diar"})
                print(f"◇ [{t:6.1f}] turn boundary (new voice)",
                      file=sys.stderr, flush=True)


def _make_handler(broadcaster):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path != "/thread":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                for frame in broadcaster.subscribe():
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # subscriber went away

    return Handler


def main():
    ap = argparse.ArgumentParser(description="B1 ariane-weaver — live STT weaver")
    ap.add_argument("--source", required=True,
                    help="video URL (live AN HLS, B2 replay, ...) — B1 is source-invariant")
    ap.add_argument("--agenda", default=None,
                    help="derouleur.json URL used as a LOOKUP DICTIONARY (agenda list "
                         "only, régie highlight ignored) to resolve heard amendment "
                         "numbers; polled ~30s, accumulated")
    ap.add_argument("--actors", default=None,
                    help="acteurs.json URL (sitting actor set) to resolve heard names "
                         "into PA uids; fetched once at startup")
    ap.add_argument("--organes", default=None,
                    help="organes.json URL (sitting groups) to label speakers' "
                         "groups; fetched once at startup")
    ap.add_argument("--out", default="thread.ndjson")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--bind", default="127.0.0.1",
                    help="SSE bind address (0.0.0.0 to serve B4 across Tailscale)")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--compute-type", default="float16",
                    help="faster-whisper compute type; int8_float16 (~1.5GB) when "
                         "the GPU is shared (desktop/ComfyUI), float16 (~3GB) otherwise")
    ap.add_argument("--user-agent", default="Mozilla/5.0",
                    help="HTTP UA for the stream (Vodalys/AN CDN needs a browser UA)")
    ap.add_argument("--referer", default=None,
                    help="HTTP Referer for the stream, e.g. https://videos.assemblee-nationale.fr/direct.<id>")
    ap.add_argument("--no-vad", dest="vad", action="store_false", default=True,
                    help="disable the silero VAD filter (VAD on by default: silence -> no output)")
    ap.add_argument("--diarize", action="store_true", default=False,
                    help="weave anonymous turn boundaries from voice changes "
                         "(pyannote segmentation-3.0 on CPU)")
    ap.add_argument("--follow", action="store_true", default=False,
                    help="reconnect when a live source dries up (B2 playlist "
                         "resets on transport moves) instead of exiting")
    args = ap.parse_args()

    seq = w.Seq()
    weaver = w.Weaver(seq=seq)
    log = w.ThreadLog(args.out)
    broadcaster = w.Broadcaster()

    # the deduction side: referentials are lookup dictionaries, nothing more
    deducer = None
    if args.agenda:
        agenda = deduce.AgendaIndex()
        deducer = deduce.Deducer(agenda, [], seq=seq)
        # every referential is polled (first fetch included): a record switch
        # or a next sitting on the live flow is picked up within one interval
        threading.Thread(target=poll_referentials,
                         args=(args.agenda, args.actors, args.organes,
                               agenda, deducer),
                         daemon=True).start()

    # single choke point so both weavers stay thread-safe
    # (ThreadLog.append is not thread-safe on its own)
    emit_lock = threading.Lock()

    def emit_base(node):
        with emit_lock:
            log.append(node)
            broadcaster.publish(node)

    def emit_node(node):
        emit_base(node)
        if deducer is None:
            return
        for extra in deducer.feed(node):  # deduced trame rides the same thread
            emit_base(extra)
            print(f"◆ [{extra['t'] / 1000:6.1f}] {extra['kind']}: {extra['text']}",
                  file=sys.stderr, flush=True)

    httpd = ThreadingHTTPServer((args.bind, args.port), _make_handler(broadcaster))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"B1 ariane-weaver: SSE on http://{args.bind}:{args.port}/thread  "
          f"(source={args.source}, agenda={args.agenda}, out={args.out})",
          file=sys.stderr, flush=True)

    diar_worker = None
    if args.diarize:
        diar_worker = DiarWorker(emit_node, seq)
        diar_worker.start()

    transcribe(args.source, weaver, emit_node, model=args.model,
               compute_type=args.compute_type,
               user_agent=args.user_agent, referer=args.referer, vad=args.vad,
               diar_worker=diar_worker, follow=args.follow)
    print("\n[done]", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
