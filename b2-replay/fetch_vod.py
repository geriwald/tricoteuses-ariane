#!/usr/bin/env python3
"""Fetch the VOD video of a captured sitting into its record's video/ dir.

B3 (record_sitting.py) does not download the video; this closes that gap for the
records captured without it. The media path is discovered from the sitting's own
data.nvs (<files>): the Vodalys base name `<num>_<YYYYMMDDHHMMSS>` yields the VOD
HLS manifest, which ffmpeg assembles into an mp4.

The output filename carries the 14-digit start stamp (hemi_<stamp>_1.mp4) — that is
the anchor B2 reads as the clock origin (origin_from_video), equal to the
liveplayer.nvs starttime. Verified path shape 2026-07-01.

Usage:
  python3 fetch_vod.py --record /mnt/data/ariane-capture/2026-06-30-soir
  python3 fetch_vod.py --record <dir> --quality 1280x720   # default
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
VODALYS_DIR = ("https://videos-an.vodalys.com/videos/definst/mp4/ida/domain1/"
               "{yyyy}/{mm}/{base}.smil/")
# HLS variant per target height (the master lists 360/540/720p by bandwidth)
_CHUNKLIST = {"640x360": "chunklist_b500000.m3u8",
              "960x540": "chunklist_b1000000.m3u8",
              "1280x720": "chunklist_b2000000.m3u8"}
# Vodalys media base: <num>_<stamp> in post-prod data.nvs, hemi_<stamp> in the
# live-captured data.nvs (both serve a VOD .smil — verified 2026-07-03)
_BASE = re.compile(r"((?:\d+|hemi)_(\d{14}))")


def _direct_id(record):
    """The sitting's direct-id, read from a supervisor log or MANIFEST."""
    for name in ("supervisor.log", "supervisor.console.log", "MANIFEST.txt"):
        p = os.path.join(record, name)
        if os.path.exists(p):
            m = re.search(r"19\d{6}_[0-9a-f]+", open(p, encoding="utf-8", errors="replace").read())
            if m:
                return m.group(0)
    raise SystemExit(f"no direct-id found in {record} (supervisor log / MANIFEST)")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def vodalys_base(record):
    """The Vodalys media base name from the sitting's data.nvs.

    Tries, in order: the local ground-truth-vod/data.nvs, the newest
    raw/data_nvs capture (no network, no direct-id needed), then the live
    endpoint via the direct-id.
    """
    candidates = [os.path.join(record, "ground-truth-vod", "data.nvs")]
    raw_nvs = sorted(glob.glob(os.path.join(record, "raw", "data_nvs", "*.nvs")))
    if raw_nvs:
        candidates.append(raw_nvs[-1])
    for path in candidates:
        if not os.path.exists(path):
            continue
        base = _base_from_nvs(open(path, "rb").read())
        if base:
            return base
    did = _direct_id(record)
    raw = _fetch(f"https://videos.assemblee-nationale.fr/Datas/an/{did}/content/data.nvs")
    base = _base_from_nvs(raw)
    if base:
        return base
    raise SystemExit(f"no Vodalys media base found in data.nvs of {record}")


def _base_from_nvs(raw):
    for f in ET.fromstring(raw).iter("file"):
        m = _BASE.search(f.attrib.get("url", ""))
        if m:
            return m.group(1), m.group(2)  # (base, stamp)
    return None


def manifest_url(base, quality="1280x720"):
    """The HLS variant URL for `quality` (a resolution the master lists)."""
    stamp = base.split("_")[1]
    d = VODALYS_DIR.format(yyyy=stamp[:4], mm=stamp[4:6], base=base)
    return d + _CHUNKLIST[quality]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True)
    ap.add_argument("--quality", default="1280x720",
                    help="HLS variant resolution to select (default 720p)")
    args = ap.parse_args()

    base, stamp = vodalys_base(args.record)
    url = manifest_url(base, args.quality)
    outdir = os.path.join(args.record, "video")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"hemi_{stamp}_1.mp4")
    if os.path.exists(out):
        raise SystemExit(f"already present: {out}")

    print(f"record : {args.record}", file=sys.stderr)
    print(f"base   : {base}", file=sys.stderr)
    print(f"manifest: {url}", file=sys.stderr)
    print(f"output : {out}", file=sys.stderr)

    # -map p:<v> would need variant probing; instead let ffmpeg pick by resolution.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats",
        "-user_agent", UA, "-i", url,
        "-c", "copy", "-bsf:a", "aac_adtstoasc", "-y", out,
    ]
    print("running:", " ".join(cmd), file=sys.stderr)
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"ffmpeg failed (rc={rc})")
    print(f"done: {out} ({os.path.getsize(out) // (1<<20)} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
