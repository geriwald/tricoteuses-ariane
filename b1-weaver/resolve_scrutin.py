"""Scrutin resolver — le chiffré global lu en direct -> l'identifiant canonique du
scrutin (issue #20, prolonge le spike 2026-07-03-scrutin-ocr).

Le nœud `kind:ballot` se tisse EN DIRECT avec l'annonce, le sort, et — via l'OCR de
l'écran-résultat incrusté (spike) — le CHIFFRÉ GLOBAL (votants/exprimés/majorité/
POUR/CONTRE). Ce que la vidéo ne porte pas : le numéro de scrutin ni le nominatif.
Ceux-là vivent dans l'open-data `assemblee.scrutins`, publié APRÈS la séance (analyse
consolidée). Ce module fait le pont : il matche le chiffré live contre l'open-data pour
résoudre `canonical.scrutin`, d'où découle ensuite le nominatif (qui a voté quoi).

Deux moitiés, comme le reste de B1 :
  - `match_scrutin(...)` : PUR (ni GPU ni réseau), le cœur testable ;
  - `fetch_scrutins(...)` : l'I/O réseau (API tricoteuses), et un CLI post-séance qui
    relit un thread.ndjson et émet les résolutions.

Honnêteté sur l'ambiguïté (comme resolve_id) : deux scrutins de la séance peuvent avoir
le même triplet (votants, pour, contre) — vu réellement le 26/06 (91/33/58 : amdt 453 ET
456). On départage alors par l'amendement appelé (le `ligne_amendement_uid` du dérouleur,
que B1 a déjà mis dans `canonical.amendement_uid`, est LITTÉRALEMENT le `amendementRefUid`
du scrutin). Faute de départage, on rend None plutôt qu'un mauvais numéro.
"""
import json
import sys
import urllib.parse
import urllib.request

# lecture OCR (event scrutin_result) -> champ open-data du scrutin
_FIELD_MAP = {
    "votants": "nombreVotants",
    "exprimes": "suffragesExprimes",
    "majorite": "nbrSuffragesRequis",
    "pour": "pour",
    "contre": "contre",
    "abstentions": "abstentions",
}


def _numbers_match(reading, scrutin):
    """Tous les compteurs présents dans la lecture égalent ceux du scrutin."""
    for ocr_key, scr_key in _FIELD_MAP.items():
        val = reading.get(ocr_key)
        if val is None:
            continue  # chiffre non lu : n'impose rien (l'OCR peut manquer une case)
        if scr_key not in scrutin or int(scrutin[scr_key]) != int(val):
            return False
    return True


def _hit(scrutin, method):
    return {
        "scrutin": scrutin["uid"],           # ce qui remplit canonical.scrutin
        "numero": scrutin.get("numero"),
        "code": scrutin.get("code"),          # adopté | rejeté ...
        "amendementRefUid": scrutin.get("amendementRefUid"),
        "objet": scrutin.get("objet"),
        "method": method,
    }


def match_scrutin(reading, scrutins, amendement_uid=None):
    """Chiffré live -> le scrutin open-data, ou None (fonction PURE).

    `reading` : dict {votants, exprimes, majorite, pour, contre, abstentions} (les
    absents sont ignorés). `scrutins` : la liste open-data d'une séance. `amendement_uid`
    : le `canonical.amendement_uid` de B1, pour départager les ex æquo chiffrés.

    Renvoie {scrutin, numero, code, amendementRefUid, objet, method} avec
    method ∈ {"chiffres", "chiffres+amendement"}, ou None si aucun / trop ambigu.
    """
    candidates = [s for s in scrutins if _numbers_match(reading, s)]
    if len(candidates) == 1:
        return _hit(candidates[0], "chiffres")
    if len(candidates) > 1 and amendement_uid:
        exact = [s for s in candidates if s.get("amendementRefUid") == amendement_uid]
        if len(exact) == 1:
            return _hit(exact[0], "chiffres+amendement")
    return None  # aucun scrutin, ou ex æquo indépartageables : honnêteté


# --------------------------------------------------------------------------- I/O

_BASE = "https://parlement.tricoteuses.fr/scrutins"


def _fetch_page(seance_uid, page, base_url, timeout):
    q = urllib.parse.urlencode({"seanceRefUid": seance_uid, "page": page})
    req = urllib.request.Request(f"{base_url}?{q}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("total", 0))
        return json.load(r).get("data", []), total


def fetch_scrutins(seance_uid, base_url=_BASE, timeout=20):
    """Tous les scrutins d'une séance depuis l'API tricoteuses (paginée, 10/page).

    `seance_uid` = le `seanceRefUid` (ex. RUANR5L17S2026IDS30769), présent dans le
    dérouleur de la séance."""
    rows, total = _fetch_page(seance_uid, 1, base_url, timeout)
    page = 2
    while len(rows) < total:
        more, _ = _fetch_page(seance_uid, page, base_url, timeout)
        if not more:
            break
        rows += more
        page += 1
    return rows


def _ocr_ballots(thread_path):
    """Les nœuds ballot chiffrés par l'OCR (source=ocr, avec `result`) d'un thread."""
    out = []
    with open(thread_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            node = json.loads(line)
            if node.get("kind") == "ballot" and node.get("source") == "ocr" \
                    and node.get("result"):
                out.append(node)
    return out


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        description="Résout canonical.scrutin en matchant le chiffré OCR d'un thread "
                    "contre l'open-data des scrutins (post-séance).")
    p.add_argument("--thread", required=True, help="thread.ndjson produit par B1")
    p.add_argument("--seance", required=True,
                   help="seanceRefUid de la séance (cf. dérouleur), pour fetch open-data")
    p.add_argument("--base", default=_BASE, help="URL de base de l'API scrutins")
    args = p.parse_args(argv)

    ballots = _ocr_ballots(args.thread)
    scrutins = fetch_scrutins(args.seance, base_url=args.base)
    print(f"[resolve_scrutin] {len(ballots)} ballot(s) OCR, "
          f"{len(scrutins)} scrutin(s) open-data pour {args.seance}", file=sys.stderr)

    for node in ballots:
        m = match_scrutin(node["result"], scrutins,
                          node.get("canonical", {}).get("amendement_uid"))
        resolved = {
            "type": "scrutin_resolved",
            "t_ms": node.get("t"),
            "ballot_seq": node.get("seq"),
            "scrutin": m["scrutin"] if m else None,
            "numero": m["numero"] if m else None,
            "code": m["code"] if m else None,
            "method": m["method"] if m else None,
        }
        print(json.dumps(resolved, ensure_ascii=False))  # NDJSON -> patch canonical.scrutin
        r = node["result"]
        tag = f"scrutin {m['numero']} ({m['method']})" if m else "NON RÉSOLU"
        print(f"  t={node.get('t')}ms  POUR={r.get('pour')} CONTRE={r.get('contre')}"
              f" votants={r.get('votants')}  -> {tag}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
