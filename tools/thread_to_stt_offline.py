#!/usr/bin/env python3
"""Extract the STT segments from a woven thread.ndjson into an stt-offline file.

The full CPU pipeline (tools/run_option3_cpu.py) transcribes once and writes a
`thread.ndjson`. Its consolidated `utterance` nodes carry `t = beg*1000` (ms since
video origin) and the recognised text — exactly what `b4-ui/demo_replay.py` needs
to re-weave the *same* thread instantly, offline, tomorrow.

Usage:
  python tools/thread_to_stt_offline.py .runs/option3-cpu-XXXX/thread.ndjson \
      data/2026-07-02-matin/stt-offline-large-v3.ndjson
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def convert(thread_path: Path, out_path: Path) -> int:
    segs = []
    with thread_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n = json.loads(line)
            if n.get("kind") == "utterance" and n.get("state") == "consolidated":
                segs.append({"beg": n["t"] / 1000.0, "text": n["text"]})
    segs.sort(key=lambda s: s["beg"])
    with out_path.open("w", encoding="utf-8") as f:
        for i, s in enumerate(segs):
            # end is optional for the weaver; fill it with the next beg (or +4s)
            end = segs[i + 1]["beg"] if i + 1 < len(segs) else s["beg"] + 4.0
            f.write(json.dumps({"beg": round(s["beg"], 2),
                                "end": round(end, 2),
                                "text": s["text"]}, ensure_ascii=False) + "\n")
    return len(segs)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    thread_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    n = convert(thread_path, out_path)
    print(f"[stt-offline] {n} segments -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
