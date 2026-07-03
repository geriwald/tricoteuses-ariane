#!/usr/bin/env python3
"""One-shot, idempotent sitting-start detection for a capture bundle.

Captures start ~15-20 min before the sitting (the supervisor arms early), so the
video opens on a mostly-silent providéo. This script finds the first SUSTAINED
speech (silero VAD via faster-whisper, CPU) and persists it once as
<record>/sitting_start.json — B2 only ever READS that file (initial seek);
nothing is computed at video-open time. Re-running is a no-op unless --force.

Run with the whisper-live venv (needs faster_whisper + numpy):
  ~/code/whisper-live/.venv/bin/python detect_start.py --record <bundle>

Primary source is the VAD (real speech start); the NVS first chapter is only
a FALLBACK when the VAD is unavailable or finds nothing — it lags real speech
(26/06: chapter at 13.9 min, first speech at 9.5 min).
"""
import argparse
import glob
import json
import os
import subprocess
import sys

SR = 16000


def first_sustained_speech(segments, window=60.0, min_density=0.5):
    """First speech start (seconds) from which speech density over the next
    `window` seconds is at least `min_density`. Segments: [(beg, end), ...].
    None if never sustained (silence or sparse announcements only)."""
    for beg, _ in segments:
        horizon = beg + window
        voiced = sum(max(0.0, min(e, horizon) - max(b, beg)) for b, e in segments)
        if voiced / window >= min_density:
            return beg
    return None


def detect(video_path, scan_minutes=30):
    """Speech-start (ms) of the video's first `scan_minutes`, by silero VAD."""
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pcm = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-t", str(scan_minutes * 60), "-i", video_path,
         "-vn", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"],
        capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    stamps = get_speech_timestamps(audio, VadOptions(min_speech_duration_ms=500))
    segments = [(s["start"] / SR, s["end"] / SR) for s in stamps]
    start_s = first_sustained_speech(segments)
    return None if start_s is None else int(start_s * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True)
    ap.add_argument("--force", action="store_true",
                    help="recompute even if sitting_start.json exists")
    args = ap.parse_args()

    out = os.path.join(args.record, "sitting_start.json")
    if os.path.exists(out) and not args.force:
        print(f"already computed: {out}", file=sys.stderr)
        return

    vids = glob.glob(os.path.join(args.record, "video", "*.mp4"))
    if not vids:
        raise SystemExit(f"no video under {args.record}")
    start_ms, method = None, None
    try:
        start_ms, method = detect(vids[0]), "vad-sustained-60s"
    except Exception as e:
        print(f"VAD unavailable ({e}) — falling back on the NVS timeline",
              file=sys.stderr)
    if start_ms is None:
        # fallback: the first NVS chapter timecode (lags real speech by minutes,
        # but far better than the cold video start)
        from replay import Record
        tl = Record(args.record).nvs_timeline()
        if not tl:
            raise SystemExit("no sustained speech and no NVS timeline")
        start_ms, method = tl[0]["t_ms"], "nvs-first-chapter"

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"sitting_start_ms": start_ms, "method": method}, f, indent=1)
    print(f"{os.path.basename(args.record.rstrip('/'))}: speech starts at "
          f"{start_ms / 60000:.1f} min -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
