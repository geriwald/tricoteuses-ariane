"""B1 ariane-weaver — the live wiring (STT + I/O side, kept out of the pure core).

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
import io
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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from ariane_env import load_dotenv

load_dotenv()
# the proven streaming stack (torch cu128 + faster-whisper): whisper_streaming's
# LocalAgreement policy, reused as-is. Point WHISPER_STREAMING_PATH at your clone
# of https://github.com/ufal/whisper_streaming (default assumes it sits next to
# this repo under ~/code/whisper-live/whisper_streaming).
_default_ws = os.path.expanduser("~/code/whisper-live/whisper_streaming")
sys.path.insert(0, os.environ.get("WHISPER_STREAMING_PATH", _default_ws))

SR = 16000


def audio_frames(source, min_chunk=1.0, user_agent=None, referer=None,
                 max_seconds=None, start_seconds=0.0):
    """Yield PCM float32 chunks from any video URL/file, via ffmpeg (-vn: audio only).

    On a live HLS playlist ffmpeg tracks the live edge by default (-live_start_index
    -3): B1 reads the present, ~30 s behind, not the DVR history. user_agent/referer
    are the HTTP headers some CDNs (Vodalys/AN) require to serve the segments.

    start_seconds seeks the input before reading (-ss): used when B1 reads a VOD file
    directly from the sitting start, so flow_s == content position and the emitted
    timestamps land exactly on the video's currentTime."""
    headers = []
    if user_agent:
        headers += ["-user_agent", user_agent]
    if referer:
        headers += ["-referer", referer]
    seek = ["-ss", f"{start_seconds:.3f}"] if start_seconds else []
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *headers, *seek,
         "-i", source, "-vn", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"],
        stdout=subprocess.PIPE,
    )
    chunk_samples = int(SR * min_chunk)
    max_samples = int(SR * max_seconds) if max_seconds is not None else None
    produced = 0
    try:
        while True:
            if max_samples is not None and produced >= max_samples:
                break
            want = chunk_samples
            if max_samples is not None:
                want = min(want, max_samples - produced)
            raw = ff.stdout.read(want * 2)
            if not raw:
                break
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            produced += len(audio)
            yield audio
    finally:
        ff.terminate()


def _with_time_offset(event, offset_s):
    if not offset_s:
        return event
    shifted = dict(event)
    for key in ("beg", "end"):
        if shifted.get(key) is not None:
            shifted[key] += offset_s
    return shifted


def _default_compute_type(device):
    return "float16" if device == "cuda" else "int8"


def _transcribe_local_agreement(source, weaver, emit_node, model="large-v3",
                                device="cuda", compute_type="float16",
                                user_agent=None, referer=None, vad=True,
                                diar_worker=None, follow=False,
                                max_seconds=None, time_offset_s=0.0,
                                start_seconds=0.0):
    """Drive Whisper over the source's audio, weaving every event into the thread."""
    from whisper_online import FasterWhisperASR, OnlineASRProcessor

    class ASR(FasterWhisperASR):
        # Expose faster-whisper's runtime knobs without touching the submodule.
        def load_model(self, modelsize, cache_dir, model_dir):
            from faster_whisper import WhisperModel
            return WhisperModel(modelsize, device=device, compute_type=compute_type,
                                download_root=cache_dir)

    print(f"[load] faster-whisper {model} on {device}/{compute_type} "
          f"(backend=local-agreement, vad={vad}) ...",
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
        for node in weaver.feed(_with_time_offset(event, time_offset_s)):
            emit_node(node)

    last_interim = ""
    captured_s = 0.0
    while True:
        remaining = None if max_seconds is None else max(0.0, max_seconds - captured_s)
        if remaining == 0.0:
            break
        for audio in audio_frames(source, user_agent=user_agent, referer=referer,
                                  max_seconds=remaining, start_seconds=start_seconds):
            captured_s += len(audio) / SR
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

        if max_seconds is not None and captured_s >= max_seconds:
            break
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


def _transcribe_chunked(source, weaver, emit_node, model="small", device="cpu",
                        compute_type="int8", user_agent=None, referer=None,
                        vad=True, diar_worker=None, follow=False,
                        max_seconds=None, time_offset_s=0.0,
                        chunk_seconds=30.0, beam=1, cpu_threads=0,
                        local_files_only=False, start_seconds=0.0):
    """CPU-friendly faster-whisper backend.

    It emits confirmed utterances after fixed-size chunks. This is less polished
    than LocalAgreement (no interim rewrites), but keeps the same B1 SSE contract
    and avoids the whisper_streaming dependency for GPU-free replay tests.
    """
    from faster_whisper import WhisperModel

    print(f"[load] faster-whisper {model} on {device}/{compute_type} "
          f"(backend=chunked, chunk={chunk_seconds:g}s, vad={vad}) ...",
          file=sys.stderr, flush=True)
    model_obj = WhisperModel(model, device=device, compute_type=compute_type,
                             cpu_threads=cpu_threads,
                             local_files_only=local_files_only)
    print("[ready] chunked transcription\n", file=sys.stderr, flush=True)

    def emit(event):
        for node in weaver.feed(_with_time_offset(event, time_offset_s)):
            emit_node(node)

    captured_s = 0.0
    started_at = time.time()
    flow_s = 0.0
    buf = []
    buf_s = 0.0

    def flush(force=False):
        nonlocal buf, buf_s, flow_s
        if not buf:
            return
        if not force and buf_s < chunk_seconds:
            return
        audio = np.concatenate(buf)
        segs, _info = model_obj.transcribe(
            audio,
            language="fr",
            beam_size=beam,
            best_of=beam,
            vad_filter=vad,
            condition_on_previous_text=False,
        )
        for s in segs:
            text = (s.text or "").strip()
            if not text:
                continue
            beg = flow_s + float(s.start)
            end = flow_s + float(s.end)
            emit({"type": "utterance", "beg": beg, "end": end, "text": text})
            print(f"✓ [{beg:6.1f}-{end:6.1f}] {text}",
                  file=sys.stderr, flush=True)
        flow_s += buf_s
        elapsed = max(time.time() - started_at, 1e-6)
        print(f"[progress] {flow_s:.1f}s source in {elapsed:.1f}s wall "
              f"({flow_s / elapsed:.2f}x realtime)",
              file=sys.stderr, flush=True)
        buf = []
        buf_s = 0.0

    while True:
        remaining = None if max_seconds is None else max(0.0, max_seconds - captured_s)
        if remaining == 0.0:
            break
        for audio in audio_frames(source, user_agent=user_agent, referer=referer,
                                  max_seconds=remaining, start_seconds=start_seconds):
            seconds = len(audio) / SR
            captured_s += seconds
            buf_s += seconds
            buf.append(audio)
            if diar_worker:
                diar_worker.push(audio)
            flush()

        flush(force=True)
        if max_seconds is not None and captured_s >= max_seconds:
            break
        if not follow:
            break
        print("[stream] source ended — reconnecting in 2s",
              file=sys.stderr, flush=True)
        time.sleep(2)


def transcribe(source, weaver, emit_node, model="large-v3", backend="local-agreement",
               device="cuda", compute_type=None, user_agent=None, referer=None,
               vad=True, diar_worker=None, follow=False, max_seconds=None,
               time_offset_s=0.0, chunk_seconds=30.0, beam=1, cpu_threads=0,
               local_files_only=False, start_seconds=0.0):
    compute_type = compute_type or _default_compute_type(device)
    if backend == "chunked":
        return _transcribe_chunked(
            source, weaver, emit_node, model=model, device=device,
            compute_type=compute_type, user_agent=user_agent, referer=referer,
            vad=vad, diar_worker=diar_worker, follow=follow,
            max_seconds=max_seconds, time_offset_s=time_offset_s,
            chunk_seconds=chunk_seconds, beam=beam, cpu_threads=cpu_threads,
            local_files_only=local_files_only, start_seconds=start_seconds)
    return _transcribe_local_agreement(
        source, weaver, emit_node, model=model, device=device,
        compute_type=compute_type, user_agent=user_agent, referer=referer,
        vad=vad, diar_worker=diar_worker, follow=follow,
        max_seconds=max_seconds, time_offset_s=time_offset_s,
        start_seconds=start_seconds)

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


def _frame_stream(source, step_s, user_agent=None, referer=None):
    """Yield (flow_s, PIL.Image) — one frame every step_s from any video source.

    A dedicated ffmpeg pipes MJPEG (fps=1/step): it tracks the live edge on an HLS
    playlist just like the audio ffmpeg, so the OCR runs on the SAME source as the STT
    (no seek — works live and on replay). flow_s ≈ frame_index * step_s, the same time
    axis the STT stamps on (± step)."""
    from PIL import Image
    headers = []
    if user_agent:
        headers += ["-user_agent", user_agent]
    if referer:
        headers += ["-referer", referer]
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *headers, "-i", source,
         "-vf", f"fps=1/{step_s:g}", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        stdout=subprocess.PIPE)
    buf = b""
    idx = 0
    try:
        while True:
            chunk = ff.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:  # split concatenated JPEGs on SOI…EOI markers
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2)
                if start < 0 or end < 0:
                    break
                jpg, buf = buf[start:end + 2], buf[end + 2:]
                yield idx * step_s, Image.open(io.BytesIO(jpg))
                idx += 1
    finally:
        ff.terminate()


class OcrWorker:
    """OCR the régie's incrusted result screen and weave a FIGURED ballot at each
    proclamation (source=ocr). Runs beside the STT on the same --source, like DiarWorker.

    The result screen carries the GLOBAL figures (votants/exprimés/majorité/POUR/CONTRE)
    but no scrutin number and no nominative vote — that is the value the compte-rendu
    service wants LIVE (issue #20). It shares the STT's Deducer so each figured ballot
    attaches to the amendment currently deduced from speech; `canonical.scrutin` stays
    None and is resolved AFTER the sitting (resolve_scrutin, off open-data).

    Detections of one screen across contiguous frames are deduped into a single event
    (modal reading, t = window midpoint), reusing the spike's pure folding."""

    def __init__(self, source, deducer, emit_node, step_s=2.0, user_agent=None,
                 referer=None, lang="fra", time_offset_s=0.0, tesseract=None):
        self._source = source
        self._deducer = deducer
        self._emit = emit_node
        self._step_s = step_s
        self._ua = user_agent
        self._ref = referer
        self._lang = lang
        self._offset = time_offset_s
        self._tesseract = tesseract

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        spike = os.path.join(REPO_ROOT, "spikes", "2026-07-03-scrutin-ocr")
        if spike not in sys.path:
            sys.path.insert(0, spike)
        import scrutin_ocr
        scrutin_ocr._resolve_tesseract(self._tesseract)
        print(f"[ocr] scanning result screens on {self._source} "
              f"(every {self._step_s:g}s)", file=sys.stderr, flush=True)

        window = []  # contiguous hit frames: (flow_s, reading)
        for flow_s, img in _frame_stream(self._source, self._step_s, self._ua, self._ref):
            reading = scrutin_ocr.read_result_screen(img, lang=self._lang)
            img.close()
            if reading is not None:
                window.append((flow_s + self._offset, reading))
            elif window:
                self._flush(window, scrutin_ocr._emit_window)
                window = []
        if window:
            self._flush(window, scrutin_ocr._emit_window)

    def _flush(self, window, fold):
        event = fold(window)  # {type, t_ms, votants…, confidence}
        for node in self._deducer.feed_scrutin_result(event):
            self._emit(node)
            r = node["result"]
            print(f"◆ [{node['t'] / 1000:6.1f}] ballot(ocr): {node['text']} "
                  f"POUR {r['pour']} / CONTRE {r['contre']} (conf {node['confidence']})",
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
    ap.add_argument("--model", default="large-v3",
                    help="faster-whisper model name/path (use small/tiny for CPU tests)")
    ap.add_argument("--backend", choices=("local-agreement", "chunked"),
                    default="local-agreement",
                    help="STT backend: whisper_streaming LocalAgreement, or a "
                         "CPU-friendly faster-whisper chunker")
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu", "auto"),
                    help="faster-whisper device")
    ap.add_argument("--compute-type", default=None,
                    help="faster-whisper compute type; default is float16 on cuda, "
                         "int8 on cpu")
    ap.add_argument("--user-agent", default="Mozilla/5.0",
                    help="HTTP UA for the stream (Vodalys/AN CDN needs a browser UA)")
    ap.add_argument("--referer", default=None,
                    help="HTTP Referer for the stream, e.g. https://videos.assemblee-nationale.fr/direct.<id>")
    ap.add_argument("--no-vad", dest="vad", action="store_false", default=True,
                    help="disable the silero VAD filter (VAD on by default: silence -> no output)")
    ap.add_argument("--diarize", action="store_true", default=False,
                    help="weave anonymous turn boundaries from voice changes "
                         "(pyannote segmentation-3.0 on CPU)")
    ap.add_argument("--ocr", action="store_true", default=False,
                    help="OCR the régie's incrusted result screen to weave FIGURED "
                         "ballot nodes (POUR/CONTRE/…); needs tesseract + Pillow")
    ap.add_argument("--ocr-step", type=float, default=2.0,
                    help="seconds between OCR frames (the result screen only stays up "
                         "~3-4s, so keep this ≤2 to catch it on several frames)")
    ap.add_argument("--ocr-lang", default="fra", help="tesseract language for the OCR")
    ap.add_argument("--tesseract", default=None,
                    help="path to the tesseract executable (else PATH / Windows default)")
    ap.add_argument("--follow", action="store_true", default=False,
                    help="reconnect when a live source dries up (B2 playlist "
                         "resets on transport moves) instead of exiting")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="stop reading/transcribing after this many source seconds")
    ap.add_argument("--time-offset-ms", type=int, default=0,
                    help="add this offset to emitted thread timestamps; useful when "
                         "B2 starts its live HLS at sitting_start_ms")
    ap.add_argument("--start-seconds", type=float, default=0.0,
                    help="seek the source this many seconds before reading (-ss); use "
                         "when B1 reads a VOD file directly from sitting_start so flow_s "
                         "== video position and timestamps match the UI's currentTime")
    ap.add_argument("--chunk-seconds", type=float, default=30.0,
                    help="chunk size for --backend chunked")
    ap.add_argument("--beam", type=int, default=1,
                    help="beam size for --backend chunked; 1 is fastest on CPU")
    ap.add_argument("--cpu-threads", type=int, default=0,
                    help="faster-whisper CPU threads; 0 lets CTranslate2 decide")
    ap.add_argument("--local-files-only", action="store_true", default=False,
                    help="do not download models; use only the local Hugging Face cache")
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

    if args.ocr:
        # share the STT Deducer so figured ballots attach to the current amendment;
        # without --agenda, a standalone Deducer still carries the figures (canonical
        # empty), leaving the STT path untouched
        ocr_deducer = deducer or deduce.Deducer(deduce.AgendaIndex(), [], seq=seq)
        OcrWorker(args.source, ocr_deducer, emit_base, step_s=args.ocr_step,
                  user_agent=args.user_agent, referer=args.referer, lang=args.ocr_lang,
                  time_offset_s=args.time_offset_ms / 1000,
                  tesseract=args.tesseract).start()

    transcribe(args.source, weaver, emit_node, model=args.model,
               backend=args.backend, device=args.device,
               compute_type=args.compute_type,
               user_agent=args.user_agent, referer=args.referer, vad=args.vad,
               diar_worker=diar_worker, follow=args.follow,
               max_seconds=args.max_seconds,
               time_offset_s=args.time_offset_ms / 1000,
               chunk_seconds=args.chunk_seconds, beam=args.beam,
               cpu_threads=args.cpu_threads,
               local_files_only=args.local_files_only,
               start_seconds=args.start_seconds)
    print("\n[done]", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
