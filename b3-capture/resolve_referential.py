#!/usr/bin/env python3
"""Post-capture referential resolution — turn a `record/` into the frozen
canonical snapshot the replay (B1) reads (spec mockup, decision 10).

ONE pass, pure Python, cron-safe end-to-end. It scans the captured raw flows for
every canonical key the replay will encounter, then resolves them against the
**Tricoteuses Parlement REST API** (`parlement.tricoteuses.fr`) — plain HTTP, no
auth, no Anubis, no MCP. That API (verified 2026-06-29) is the machine-to-machine
access `tricoteuses-ariane` itself will use in production: a service cannot depend
on an interactive OAuth MCP. The MCP (Moulineuse) was an exploration crutch; the
REST API is the real door. (Anubis protects only the Forgejo/site, not the data API.)

Keys lifted from the raw flows (field names verified against a live dérouleur
2026-06-29):
  - dérouleur ADT lines: depute_tribun_id (author), ligne_amendement_uid, texte_bibard;
  - data.nvs <speaker><url>: the speaker's tribun id.
Actor uid = "PA" + tribun_id (the #9 bridge, 136/136 on the FIN DE VIE capture).

Resolved slices (flat fields straight off the API, ready for B1's clickable labels):
  acteurs.json      uid, civ, prenom, nom, slug, groupe_uid
  organes.json      uid, libelle, libelle_abrege, code_type    (groups + chamber)
  amendements.json  uid, numero, auteur_ref, groupe_ref, division, sort
  documents.json    uid, titre, type    (L17 proposition + rapport)

Output under <record>/referential/:
  _keys.json     the frozen key set (audit trail / re-resolution input)
  {acteurs,organes,amendements,documents}.json   the resolved slices

Usage:
  python resolve_referential.py --record /mnt/data/ariane-capture/2026-06-26-evening
  python resolve_referential.py --record DIR --keys-only   # extract, skip the API

No third-party deps (urllib only). Idempotent: re-running overwrites the slices.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from glob import glob

API = "https://parlement.tricoteuses.fr"
UA = "ariane-resolver/0.1 (AN hackathon; tricoteuses-ariane)"
TRIBUN_RE = re.compile(r"(\d+)")   # the <speaker><url> is the bare tribun id

# Mnémosyne (Telegram) ping via the mnemo-send skill — close the loop so the end
# of the canutes resolution is visible. Best-effort: never breaks the resolution.
MNEMO_SEND = str(pathlib.Path("~/.claude/skills/mnemo-send/send.sh").expanduser())


def notify(text):
    try:
        subprocess.run([MNEMO_SEND], input=text, text=True, timeout=30, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
# uids per request — the API 400s above ~25 uid[] (measured 2026-06-29); confirm
# the real limit with Emmanuel. 20 is a safe margin.
BATCH = 20


# ---- stage A: extract canonical keys from the captured raw flows -------------

def extract_derouleur_keys(path, tribun_ids, amdt_uids, bibards):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"  skip {os.path.basename(path)}: {e}", file=sys.stderr)
        return
    phases = d.get("racine", {}).get("contenu", {}).get("phase", [])
    phases = phases if isinstance(phases, list) else [phases]
    for ph in phases:
        lg = ph.get("ligne", [])
        lg = lg if isinstance(lg, list) else [lg]
        for ln in lg:
            if ln.get("depute_tribun_id"):
                tribun_ids.add(str(ln["depute_tribun_id"]))
            if ln.get("ligne_amendement_uid"):
                amdt_uids.add(ln["ligne_amendement_uid"])
            if ln.get("texte_bibard"):
                bibards.add(str(ln["texte_bibard"]))


def extract_nvs_keys(path, tribun_ids):
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        print(f"  skip {os.path.basename(path)}: {e}", file=sys.stderr)
        return
    sps = root.find("speakers")
    for s in (sps if sps is not None else []):
        m = TRIBUN_RE.search((s.findtext("url") or "").strip())
        if m:
            tribun_ids.add(m.group(1))


def extract_keys(record):
    raw = os.path.join(record, "raw")
    der = sorted(glob(os.path.join(raw, "derouleur", "*.json")))
    nvs = sorted(glob(os.path.join(raw, "data_nvs", "*.nvs")))
    tribun_ids, amdt_uids, bibards = set(), set(), set()
    print(f"scanning {len(der)} dérouleur + {len(nvs)} data.nvs snapshots…")
    for p in der:
        extract_derouleur_keys(p, tribun_ids, amdt_uids, bibards)
    for p in nvs:
        extract_nvs_keys(p, tribun_ids)
    return {"tribun_ids": sorted(tribun_ids),
            "amendment_uids": sorted(amdt_uids),
            "bibards": sorted(bibards)}


# ---- stage B: resolve the keys against the Parlement REST API ----------------

def api_get(resource, uids):
    """GET <resource> for a set of uids, batched. Returns the rows whose uid is
    in the requested set (the API's uid filter is not always exact-match, so we
    re-filter client-side). One retry on transient error, then skip the batch."""
    wanted = set(uids)
    out = {}
    for i in range(0, len(uids), BATCH):
        chunk = uids[i:i + BATCH]
        qs = urllib.parse.urlencode([("uid[]", u) for u in chunk] + [("perPage", len(chunk) * 2)])
        url = f"{API}/{resource}?{qs}"
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    rows = json.loads(r.read()).get("data", [])
                for row in rows:
                    if row.get("uid") in wanted:
                        out[row["uid"]] = row
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  {resource}: batch {i // BATCH} failed ({e}) — skipped", file=sys.stderr)
                else:
                    time.sleep(1.0)
        time.sleep(0.2)   # politeness between batches
    return [out[u] for u in uids if u in out]


def slice_acteurs(rows):
    return [{"uid": r.get("uid"), "civ": r.get("civ"),
             "prenom": r.get("prenom"), "nom": r.get("nom"), "slug": r.get("slug"),
             "groupe_uid": r.get("groupeParlementaireUid")} for r in rows]


def slice_organes(rows):
    return [{"uid": r.get("uid"), "libelle": r.get("libelle"),
             "libelle_abrege": r.get("libelleAbrege"), "code_type": r.get("codeType")} for r in rows]


def slice_amendements(rows):
    return [{"uid": r.get("uid"), "numero": r.get("numeroLong"),
             "auteur_ref": r.get("acteurRefUid"), "groupe_ref": r.get("groupePolitiqueRefUid"),
             "division": r.get("divisionTitre") or r.get("divisionArticleDesignationCourte"),
             "sort": r.get("sortEnSeance") or r.get("sort")} for r in rows]


def slice_documents(rows):
    return [{"uid": r.get("uid"), "titre": r.get("titrePrincipal"),
             "type": r.get("typeLibelle")} for r in rows]


def api_documents_by_bibard(bibards):
    """Resolve the text + report(s) for each bibard. The /documents endpoint
    IGNORES the uid filter and its `search` only matches the title (measured
    2026-06-29 — flag to Emmanuel); the working filter is `numNotice=<bibard>`
    + `legislature=17`. Keeps every L17 hit (proposition + rapport(s))."""
    out = {}
    for b in bibards:
        qs = urllib.parse.urlencode([("numNotice", b), ("legislature", 17), ("perPage", 50)])
        try:
            req = urllib.request.Request(f"{API}/documents?{qs}",
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rows = json.loads(r.read()).get("data", [])
        except Exception as e:
            print(f"  documents: numNotice {b} failed ({e})", file=sys.stderr)
            continue
        for row in rows:
            if row.get("uid") and row.get("typeLibelle"):   # skip the untyped raw-text rows
                out[row["uid"]] = row
        time.sleep(0.2)
    return list(out.values())


def resolve(record, keys):
    refdir = os.path.join(record, "referential")
    os.makedirs(refdir, exist_ok=True)

    def write(name, rows):
        json.dump(rows, open(os.path.join(refdir, f"{name}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"  {name}.json: {len(rows)} rows")

    # actors: uid = 'PA' + tribun_id
    actor_uids = ["PA" + t for t in keys["tribun_ids"]]
    acteurs = slice_acteurs(api_get("acteurs", actor_uids))
    write("acteurs", acteurs)
    if len(acteurs) < len(actor_uids):
        print(f"  note: {len(actor_uids) - len(acteurs)} tribun ids did not resolve to a PA "
              f"actor (chair / unkeyed voice — the #9 gap, expected).")

    amendements = slice_amendements(api_get("amendements", keys["amendment_uids"]))
    write("amendements", amendements)

    # documents: search by bibard (the uid filter is ignored on /documents)
    documents = slice_documents(api_documents_by_bibard(keys["bibards"]))
    write("documents", documents)

    # organes: union of actor groups + amendment groups + the chamber organe
    pos = {a["groupe_uid"] for a in acteurs if a.get("groupe_uid")}
    pos |= {a["groupe_ref"] for a in amendements if a.get("groupe_ref")}
    organes = slice_organes(api_get("organes", sorted(pos)))
    write("organes", organes)
    return {"acteurs": len(acteurs), "amendements": len(amendements),
            "organes": len(organes), "documents": len(documents)}


# ---- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True,
                    help="capture dir (holds raw/derouleur/, raw/data_nvs/)")
    ap.add_argument("--keys-only", action="store_true",
                    help="extract keys to _keys.json and stop (no API calls)")
    args = ap.parse_args()

    keys = extract_keys(args.record)
    refdir = os.path.join(args.record, "referential")
    os.makedirs(refdir, exist_ok=True)
    json.dump(keys, open(os.path.join(refdir, "_keys.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"extracted: {len(keys['tribun_ids'])} tribun ids, "
          f"{len(keys['amendment_uids'])} amendment uids, {len(keys['bibards'])} bibards "
          f"-> {refdir}/_keys.json")
    if args.keys_only:
        return 0

    print(f"resolving against {API} …")
    rec = os.path.basename(os.path.normpath(args.record))
    try:
        c = resolve(args.record, keys)
    except Exception as e:
        notify(f"Ariane: PROBLEME — resolution des referentiels echouee ({type(e).__name__}: {e}). "
               f"Capture: {rec}. A relancer.")
        raise
    print("done. referential snapshot frozen in referential/ — B1 reads it statically.")
    notify(f"Ariane: referentiels canutes resolus pour {rec} — "
           f"{c['acteurs']} acteurs, {c['amendements']} amendements, "
           f"{c['organes']} groupes, {c['documents']} documents. Snapshot fige.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
