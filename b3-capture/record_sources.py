#!/usr/bin/env python3
"""Record AN live sources (dérouleur, data.nvs, Eliasse) with wall-clock stamps.

Goal — AN-internal REAL-TIME tool. The public video is delayed ~5 min (régie
production time, during which editorial files like the NVS are hand-filled).
This recorder archives every source with a wall-clock stamp so you can later
align them to that delay and see WHICH document is populated at TRUE real time
(leads the broadcast) vs which only appears in sync with the delayed video.

Three sources:
  - dérouleur : www.assemblee-nationale.fr/local/derouleur/derouleur.json (cached ~5s)
  - NVS       : videos.assemblee-nationale.fr/.../data.nvs  (editorial, hand-keyed)
  - Eliasse   : eliasse.assemblee-nationale.fr/eliasse/...  (applicative, ~1s)

Writes under --outdir:
  index.ndjson            one compact JSON record per tick (state of each source)
  raw/<source>/<ts>.*     full raw responses (the time-stamped "cache")

Eliasse TLS: its chain (Gandi intermediate) is not in the default CA bundle, so
we use an UNVERIFIED ssl context for that host only. Measurement-only shortcut;
inside the AN the internal CA is trusted. Pass --verify-eliasse to force verify.

No third-party deps. Ctrl-C to stop.
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
DEROULEUR_URL = "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json"
ELIASSE_BASE = "https://eliasse.assemblee-nationale.fr/eliasse"
_NUM = re.compile(r"n[°o]\s*(\d+)")
_INSECURE = ssl._create_unverified_context()


def now() -> datetime:
    return datetime.now()


def stamp(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S.%f")[:-3]


def fetch(url: str, referer: str, insecure: bool = False) -> bytes:
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}modulo={int(time.time() * 1000)}"
    req = urllib.request.Request(full, headers={
        "User-Agent": UA,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, application/xml, text/xml, */*; q=0.01",
    })
    ctx = _INSECURE if insecure else None
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.read()


def amdt_num(label: str):
    m = _NUM.search(label or "")
    return m.group(1) if m else None


# ---- per-source state extraction --------------------------------------------

def state_derouleur(raw: bytes) -> dict:
    d = json.loads(raw)
    phases = d["racine"]["contenu"].get("phase", [])
    if isinstance(phases, dict):           # sometimes a single object, sometimes a list
        phases = [phases]
    lignes, active_label = [], ""
    for ph in phases:
        pls = ph.get("ligne", [])
        lignes.extend(pls)
        if any(ln.get("ligne_video_highlighted") == "true" for ln in pls):
            active_label = ph.get("phase_libelle", "")
    if not active_label and phases:
        active_label = phases[-1].get("phase_libelle", "")
    hl = [
        ((ln.get("ligne_libelle_1") or "").strip(),
         (ln.get("depute_tribun_id") or "").strip())
        for ln in lignes if ln.get("ligne_video_highlighted") == "true"
    ]
    cursor = hl[3] if len(hl) > 3 else (hl[-1] if hl else None)
    return {
        "extract": d["racine"]["jaune"].get("extract_date_time", ""),
        "phase": active_label,
        "n_highlighted": len(hl),
        "cursor_label": cursor[0] if cursor else None,
        "cursor_num": amdt_num(cursor[0]) if cursor else None,
        "cursor_tribun": cursor[1] if cursor else None,
    }


def state_nvs(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    spk = {}
    sps = root.find("speakers")
    for s in (sps if sps is not None else []):
        spk[s.attrib.get("id")] = ((s.findtext("name") or "").strip(),
                                    (s.findtext("url") or "").strip())
    seq = []

    def walk(e):
        label = (e.attrib.get("label") or "").strip()
        ty = e.find("type")
        sp = e.find("speaker")
        name, tribun = ("", "")
        if sp is not None:
            name, tribun = spk.get(sp.attrib.get("id"), ("", ""))
        if label:
            seq.append((label, ty.attrib.get("value") if ty is not None else "", name, tribun))
        for c in e:
            if c.tag == "chapter":
                walk(c)

    ch = root.find("chapters")
    if ch is not None:
        walk(ch)
    last = seq[-1] if seq else ("", "", "", "")
    return {
        "status": root.attrib.get("status", ""),
        "n_chapters": len(seq),
        "last_label": last[0],
        "last_type": last[1],
        "last_speaker": last[2] or None,
        "last_tribun": last[3] or None,
    }


def state_eliasse(insecure: bool) -> dict:
    ref = f"{ELIASSE_BASE}/index.html"
    proc = json.loads(fetch(f"{ELIASSE_BASE}/prochainADiscuter.do?page=1&start=0&limit=25",
                            ref, insecure)).get("prochainADiscuter", {})
    out = {
        "bibard": proc.get("bibard"),
        "numAmdt": proc.get("numAmdt"),
        "organe": proc.get("organeAbrv"),
        "sort": None, "etat": None, "place": None,
    }
    # detail of the current amendment (sortEnSeance, place, etat)
    if proc.get("numAmdt"):
        q = (f"{ELIASSE_BASE}/amendement.do?legislature={proc.get('legislature', '17')}"
             f"&bibard={proc['bibard']}&bibardSuffixe={proc.get('bibardSuffixe', '')}"
             f"&organeAbrv={proc.get('organeAbrv', 'AN')}&numAmdt={proc['numAmdt']}"
             f"&page=1&start=0&limit=25")
        try:
            amds = json.loads(fetch(q, ref, insecure)).get("amendements", [])
            if amds:
                a = amds[0]
                out["sort"] = a.get("sortEnSeance")
                out["etat"] = a.get("etat")
                out["place"] = a.get("placeReference")
        except Exception as e:
            out["detail_error"] = str(e)
    return out


# ---- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--direct-id", required=True,
                    help="id from videos.assemblee-nationale.fr/direct.<ID>")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--outdir", default="record")
    ap.add_argument("--verify-eliasse", action="store_true",
                    help="verify Eliasse TLS (fails without the Gandi intermediate)")
    args = ap.parse_args()
    insecure = not args.verify_eliasse

    nvs_ref = f"https://videos.assemblee-nationale.fr/direct.{args.direct_id}"
    nvs_url = (f"https://videos.assemblee-nationale.fr/Datas/an/"
               f"{args.direct_id}/content/data.nvs")

    os.makedirs(args.outdir, exist_ok=True)
    for s in ("derouleur", "nvs", "eliasse"):
        os.makedirs(os.path.join(args.outdir, "raw", s), exist_ok=True)
    index = open(os.path.join(args.outdir, "index.ndjson"), "a", encoding="utf-8", buffering=1)

    def save_raw(source: str, ts: str, ext: str, raw: bytes):
        with open(os.path.join(args.outdir, "raw", source, f"{ts}.{ext}"), "wb") as f:
            f.write(raw)

    print(f"recording -> {args.outdir}/  (interval {args.interval}s, Ctrl-C to stop)",
          file=sys.stderr)
    if insecure:
        print("note: Eliasse TLS NOT verified (Gandi intermediate missing locally)",
              file=sys.stderr)

    prev = {"der": None, "nvs": None, "eli": None}

    while True:
        wall = now()
        ts = wall.strftime("%H%M%S_%f")[:-3]
        rec = {"wall": wall.isoformat(timespec="milliseconds")}

        for source, ext, getter in (
            ("derouleur", "json", lambda: fetch(DEROULEUR_URL, nvs_ref)),
            ("nvs", "nvs", lambda: fetch(nvs_url, nvs_ref)),
        ):
            try:
                raw = getter()
                save_raw(source, ts, ext, raw)
                rec[source] = (state_derouleur if source == "derouleur" else state_nvs)(raw)
            except Exception as e:
                rec[source] = {"error": str(e)}

        try:
            rec["eliasse"] = state_eliasse(insecure)
        except Exception as e:
            rec["eliasse"] = {"error": str(e)}

        index.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # compact change-log on stdout (only when a key signal moves)
        der_k = (rec.get("derouleur") or {}).get("cursor_num")
        nvs_k = (rec.get("nvs") or {}).get("last_label")
        eli_k = (rec.get("eliasse") or {}).get("numAmdt")
        if der_k != prev["der"]:
            print(f"[{stamp(wall)}] DEROULEUR cursor#{der_k} "
                  f"(extract {rec['derouleur'].get('extract', '')})", flush=True)
            prev["der"] = der_k
        if eli_k != prev["eli"]:
            e = rec["eliasse"]
            print(f"[{stamp(wall)}] ELIASSE   prochain#{eli_k} bibard {e.get('bibard')} "
                  f"sort={e.get('sort')} place={e.get('place')}", flush=True)
            prev["eli"] = eli_k
        if nvs_k != prev["nvs"]:
            n = rec["nvs"]
            who = f" | {n.get('last_speaker')}" if n.get("last_speaker") else ""
            print(f"[{stamp(wall)}] NVS       {nvs_k!r}{who}", flush=True)
            prev["nvs"] = nvs_k

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)
