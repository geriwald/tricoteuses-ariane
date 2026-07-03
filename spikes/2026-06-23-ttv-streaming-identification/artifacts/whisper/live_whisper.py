"""Whisper live streaming via whisper_streaming (LocalAgreement), with interim exposure.
Source: --file <wav> (paced at 1x with ffmpeg -re => simulated live), or --url <stream> (real live).
Console: '⋯' = interim (rewritten in place), '✓' = confirmed utterance.
--out <file.ndjson>: structured log of every interim + utterance (reusable, e.g. for a UI)."""
import argparse
import json
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, "/home/geraud/code/whisper-live/whisper_streaming")
from whisper_online import FasterWhisperASR, OnlineASRProcessor  # noqa: E402

SR = 16000

ap = argparse.ArgumentParser()
ap.add_argument("--file")
ap.add_argument("--url")
ap.add_argument("--model", default="large-v3")
ap.add_argument("--min-chunk", type=float, default=1.0)
ap.add_argument("--out", help="NDJSON log of interim + utterance events")
args = ap.parse_args()

ff_in = ["-re", "-i", args.file] if args.file else (["-i", args.url] if args.url else None)
if ff_in is None:
    sys.exit("need --file or --url")

ff = subprocess.Popen(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", *ff_in, "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"],
    stdout=subprocess.PIPE,
)
out = open(args.out, "w") if args.out else None


def log(ev):
    if out:
        out.write(json.dumps(ev, ensure_ascii=False) + "\n")
        out.flush()


print(f"[load] faster-whisper {args.model} on cuda/float16 ...", file=sys.stderr, flush=True)
asr = FasterWhisperASR("fr", args.model)
online = OnlineASRProcessor(asr)
print("[ready] streaming  (⋯ = interim provisoire, ✓ = utterance confirmée)\n", file=sys.stderr, flush=True)

chunk_bytes = int(SR * args.min_chunk) * 2
t0 = time.time()
last_interim = ""
try:
    while True:
        raw = ff.stdout.read(chunk_bytes)
        if not raw:
            break
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        online.insert_audio_chunk(audio)
        now = round(time.time() - t0, 2)

        cbeg, cend, ctext = online.process_iter()  # confirmed (LocalAgreement)
        if ctext:
            sys.stderr.write("\r" + " " * 110 + "\r")
            print(f"✓ [{cbeg:6.1f}-{cend:6.1f}] {ctext}", file=sys.stderr, flush=True)
            log({"type": "utterance", "t": now, "beg": round(cbeg, 2), "end": round(cend, 2), "text": ctext})
            last_interim = ""

        ibeg, iend, itext = online.to_flush(online.transcript_buffer.complete())  # interim (unconfirmed)
        itext = (itext or "").strip()
        if itext and itext != last_interim:
            sys.stderr.write(f"\r⋯ {itext[:108]}")
            sys.stderr.flush()
            log({"type": "interim", "t": now, "text": itext})
            last_interim = itext
finally:
    fbeg, fend, ftext = online.finish()
    if ftext:
        sys.stderr.write("\r" + " " * 110 + "\r")
        print(f"✓ [FINAL {fbeg:.1f}-{fend:.1f}] {ftext}", file=sys.stderr, flush=True)
        log({"type": "utterance", "t": round(time.time() - t0, 2), "beg": round(fbeg, 2),
             "end": round(fend, 2), "text": ftext, "final": True})
    ff.terminate()
    if out:
        out.close()
    print(f"\n[done] wall-clock {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
