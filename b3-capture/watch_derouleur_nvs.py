#!/usr/bin/env python3
"""Watch the AN live dérouleur and the video-CDN NVS, logging every state change.

Goal: let a human measure the lag between
  - the video overlay (incrustation)  <->  derouleur.json (amendment trame)
  - the HTML "Sommaire"               <->  data.nvs (real thread + speakers)

Only state CHANGES are printed (deduped), each with a millisecond wall-clock
timestamp, so you can eyeball them against what you see/hear in the live stream.

No third-party deps (urllib + xml.etree + json only).

Usage:
    python watch_derouleur_nvs.py --direct-id 19234018_6a3cce7061b3e
    # --direct-id is the id in the live URL:
    #   https://videos.assemblee-nationale.fr/direct.<DIRECT_ID>
    # optional: --interval 3.0  --out derouleur-nvs-sync.log

Stop with Ctrl-C.
"""
import argparse
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
DEROULEUR_URL = "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json"


def now_ms() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def fetch(url: str, referer: str) -> bytes:
    """GET with browser UA + referer + a cache-busting `modulo` param."""
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}modulo={int(time.time() * 1000)}"
    req = urllib.request.Request(full, headers={
        "User-Agent": UA,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/xml, text/xml, application/json, */*; q=0.01",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


# ---- dérouleur (JSON) --------------------------------------------------------

def parse_derouleur(raw: bytes):
    """Return (extract_date_time, highlighted) where highlighted is a list of
    (label, tribun_id) for every line with ligne_video_highlighted == 'true'."""
    d = json.loads(raw)
    jaune = d["racine"]["jaune"]
    phase = d["racine"]["contenu"]["phase"]
    lignes = phase.get("ligne", [])
    highlighted = [
        ((ln.get("ligne_libelle_1") or "").strip(),
         (ln.get("depute_tribun_id") or "").strip())
        for ln in lignes
        if ln.get("ligne_video_highlighted") == "true"
    ]
    return jaune.get("extract_date_time", ""), highlighted


# HYPOTHESIS to validate against the video's bold line: within the highlighted
# block the live cursor sits at index 3, right after 3 context anchors
# (article header, main amendment, first sub-amendment). Observed on 3 points.
CURSOR_INDEX = 3


def derouleur_cursor(highlighted):
    """Best guess at the current bold line: the entry at CURSOR_INDEX."""
    if len(highlighted) > CURSOR_INDEX:
        return highlighted[CURSOR_INDEX]
    return highlighted[-1] if highlighted else None


# ---- NVS (XML) ---------------------------------------------------------------

def parse_nvs(raw: bytes):
    """Return ordered list of chapter entries: (label, type_value, speaker, tribun)."""
    root = ET.fromstring(raw)
    # speaker id -> (name, tribun id stored in <url>)
    spk = {}
    sps = root.find("speakers")
    for s in (sps if sps is not None else []):
        spk[s.attrib.get("id")] = (
            (s.findtext("name") or "").strip(),
            (s.findtext("url") or "").strip(),
        )
    out = []

    def walk(e):
        ty = e.find("type")
        tyv = ty.attrib.get("value") if ty is not None else ""
        label = (e.attrib.get("label") or "").strip()
        sp = e.find("speaker")
        name, tribun = "", ""
        if sp is not None:
            name, tribun = spk.get(sp.attrib.get("id"), ("", ""))
        if label:
            out.append((label, tyv, name, tribun))
        for c in e:
            if c.tag == "chapter":
                walk(c)

    chapters = root.find("chapters")
    if chapters is not None:
        walk(chapters)
    return out


# ---- main loop ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--direct-id", required=True,
                    help="id from https://videos.assemblee-nationale.fr/direct.<ID>")
    ap.add_argument("--interval", type=float, default=1.0, help="poll seconds")
    ap.add_argument("--out", default="derouleur-nvs-sync.log", help="log file")
    args = ap.parse_args()

    nvs_base = f"https://videos.assemblee-nationale.fr/Datas/an/{args.direct_id}/content"
    nvs_url = f"{nvs_base}/data.nvs"
    nvs_ref = f"https://videos.assemblee-nationale.fr/direct.{args.direct_id}"

    out = open(args.out, "a", encoding="utf-8", buffering=1)

    def log(source: str, msg: str):
        line = f"[{now_ms()}] {source:9s} | {msg}"
        print(line, flush=True)
        out.write(line + "\n")

    log("START", f"interval={args.interval}s  nvs={nvs_url}")
    print("(only state changes are logged; Ctrl-C to stop)", file=sys.stderr)

    prev_der = None        # (label, tribun) cursor at CURSOR_INDEX
    prev_nvs = None        # tuple of nvs entries
    prev_nvs_set = set()

    while True:
        # --- dérouleur : on logge quand le CURSEUR (pos 3) change ---
        try:
            extract_dt, hl = parse_derouleur(fetch(DEROULEUR_URL, nvs_ref))
            cursor = derouleur_cursor(hl)          # (label, tribun) at CURSOR_INDEX
            if cursor != prev_der:
                anchors = " > ".join(lbl for lbl, _ in hl[:CURSOR_INDEX])
                if cursor:
                    label, tribun = cursor
                    log("DEROULEUR", f"curseur(pos{CURSOR_INDEX})= {label} (tribun {tribun}) "
                                     f"| extract={extract_dt} | bloc={len(hl)} | ancres: {anchors}")
                else:
                    log("DEROULEUR", f"curseur=vide | extract={extract_dt} | bloc={len(hl)}")
                prev_der = cursor
        except Exception as e:  # network hiccup, stale cache, etc.
            print(f"[{now_ms()}] derouleur err: {e}", file=sys.stderr)

        # --- nvs ---
        try:
            entries = parse_nvs(fetch(nvs_url, nvs_ref))
            sig = tuple(entries)
            if sig != prev_nvs:
                cur_set = set(entries)
                new = [e for e in entries if e not in prev_nvs_set]
                if prev_nvs is None:
                    log("NVS", f"init: {len(entries)} chapitres (dernier: {entries[-1] if entries else '-'})")
                else:
                    for label, tyv, name, tribun in new:
                        who = f" | {name} (tribun {tribun})" if name else ""
                        log("NVS", f"+ [{tyv}] {label}{who}")
                    if not new:
                        log("NVS", "(structure modifiée sans nouveau chapitre)")
                prev_nvs = sig
                prev_nvs_set = cur_set
        except Exception as e:
            print(f"[{now_ms()}] nvs err: {e}", file=sys.stderr)

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)
