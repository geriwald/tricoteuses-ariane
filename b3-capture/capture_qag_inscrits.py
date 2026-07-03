#!/usr/bin/env python3
"""Capture the QAG view of the AN dérouleur (INSCRITQAG lines) — issue #19.

The official Tricoteuses doc (docs/derouleur-api.md) lists `INSCRITQAG`
("Inscrit pour questions au Gouvernement") as a line type but gives NO schema
for it (only `ADT` is documented). This script captures a real sample on a QAG
day (Tue/Wed ~15h) and freezes the observed field set.

It fetches the public dérouleur JSON (browser UA + referer + cache-buster, same
politeness as watch_derouleur_nvs.py), keeps the raw file, extracts every
INSCRITQAG line, and prints the union of fields seen (the empirical schema).

On a non-QAG day the dérouleur carries ARTICLE/ADT/SSADT instead: the script
says so and exits 1, so a scheduler can tell "ran too early / wrong day".

Usage:
    python capture_qag_inscrits.py [--out-dir DIR]

No third-party deps (urllib + json only).
"""
import argparse
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")
DEROULEUR_URL = "https://www.assemblee-nationale.fr/local/derouleur/derouleur.json"
REFERER = "https://www.assemblee-nationale.fr/dyn/seance-publique/derouleur"


def fetch(url: str) -> bytes:
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}modulo={int(time.time() * 1000)}"
    req = urllib.request.Request(full, headers={
        "User-Agent": UA,
        "Referer": REFERER,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, */*; q=0.01",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def lines_of(d: dict) -> list:
    phase = d["racine"]["contenu"]["phase"]
    if isinstance(phase, list):  # multi-phase shape
        out = []
        for ph in phase:
            lg = ph.get("ligne", [])
            out += lg if isinstance(lg, list) else [lg]
        return out
    lg = phase.get("ligne", [])
    return lg if isinstance(lg, list) else [lg]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw = fetch(DEROULEUR_URL)
    d = json.loads(raw)

    jaune = d["racine"]["jaune"]
    phase = d["racine"]["contenu"]["phase"]
    phase0 = phase[0] if isinstance(phase, list) and phase else phase
    lignes = lines_of(d)
    types = Counter((ln.get("ligne_type") or "?") for ln in lignes)

    print(f"jaune id={jaune.get('id')} jaune_date_time={jaune.get('jaune_date_time')} "
          f"extract={jaune.get('extract_date_time')}")
    if isinstance(phase0, dict):
        print(f"phase_libelle={phase0.get('phase_libelle')!r} "
              f"phase_type={phase0.get('phase_type')!r}")
    print(f"lines={len(lignes)} types={dict(types)}")

    qag = [ln for ln in lignes if ln.get("ligne_type") == "INSCRITQAG"]

    # Always keep the raw capture (cheap, lets us re-derive anything).
    raw_path = f"{args.out_dir}/derouleur-{stamp}.json"
    with open(raw_path, "wb") as f:
        f.write(raw)
    print(f"raw saved -> {raw_path}")

    if not qag:
        print("\n>> NO INSCRITQAG line. Not a QAG day (or session not yet open).",
              file=sys.stderr)
        return 1

    # Empirical schema: union of keys + per-key fill rate + value sample.
    fields = Counter()
    for ln in qag:
        fields.update(ln.keys())
    schema = {k: {"present": fields[k], "of": len(qag),
                  "sample": next((ln[k] for ln in qag if ln.get(k)), None)}
              for k in sorted(fields)}

    qag_path = f"{args.out_dir}/inscritqag-{stamp}.json"
    with open(qag_path, "w", encoding="utf-8") as f:
        json.dump({"jaune": jaune, "phase": phase0 if isinstance(phase0, dict) else None,
                   "count": len(qag), "schema": schema, "lines": qag},
                  f, ensure_ascii=False, indent=2)
    print(f"\n>> {len(qag)} INSCRITQAG lines captured -> {qag_path}")
    print("Observed fields:")
    for k, info in schema.items():
        print(f"  {k:42s} {info['present']}/{info['of']}  e.g. {info['sample']!r}")
    print("\nFirst 3 lines:")
    for ln in qag[:3]:
        print("  " + json.dumps(ln, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
