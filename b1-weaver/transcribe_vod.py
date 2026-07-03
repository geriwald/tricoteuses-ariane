"""Spike (2026-07-01): offline Whisper on a downloaded VOD mp4 -> real STT output.

The point: get REAL transcriptions of full sittings (not simulated noise) to feed a
genuine end-to-end eval of canonical-ID resolution, and to see offline STT quality.
Offline large-v3 with beam search + VAD filter (drops silence/hallucinations).
Faster than real time (spike RTF ~0.13), writes incrementally so it can be watched
and inspected mid-run.

  python transcribe_vod.py --video /mnt/data/ariane-capture/2026-06-26-evening/video/hemi_*.mp4 \
                           --out  /mnt/data/ariane-capture/2026-06-26-evening/stt-offline-large-v3.ndjson
"""
import argparse
import json
import subprocess
import sys
import time


def duration_s(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--compute-type", default="int8_float16",
                    help="int8_float16 (~1.5GB, default) fits the shared 8GB GPU; float16 (~3GB) may OOM")
    ap.add_argument("--no-vad", dest="vad", action="store_false", default=True)
    ap.add_argument("--no-condition", dest="condition", action="store_false", default=True,
                    help="disable condition_on_previous_text (prevents hallucination-loop runaway / OOM)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    total = duration_s(args.video)
    print(f"[load] {args.model} cuda/{args.compute_type} | video {total:.0f}s | vad={args.vad}", file=sys.stderr, flush=True)
    model = WhisperModel(args.model, device="cuda", compute_type=args.compute_type)

    segs, info = model.transcribe(args.video, language="fr", beam_size=args.beam,
                                  vad_filter=args.vad, condition_on_previous_text=args.condition)
    t0 = time.time()
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(json.dumps({"beg": round(s.start, 2), "end": round(s.end, 2),
                                "text": s.text.strip()}, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 25 == 0:
                pct = (100 * s.end / total) if total else 0
                rt = s.end / (time.time() - t0) if time.time() > t0 else 0
                print(f"  {n} segs | {s.end:6.0f}/{total:.0f}s ({pct:4.1f}%) | {rt:.1f}x realtime",
                      file=sys.stderr, flush=True)
    print(f"[done] {n} segments in {time.time() - t0:.0f}s -> {args.out}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
