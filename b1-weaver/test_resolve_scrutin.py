"""Tests du scrutin resolver (match chiffré live -> scrutin open-data).

Fixture inline : les vrais chiffres de la séance du 26/06 (extraits de
parlement.tricoteuses.fr), dont la collision réelle 91/33/58 sur les amendements 453
ET 456 — le cas qui force le départage par amendement.
"""
import json
import os

import pytest

import resolve_scrutin as rs


def _s(uid, numero, votants, expr, req, pour, contre, abst, amdt_n, objet):
    return {"uid": uid, "numero": numero, "code": "rejeté",
            "nombreVotants": votants, "suffragesExprimes": expr,
            "nbrSuffragesRequis": req, "pour": pour, "contre": contre,
            "abstentions": abst,
            "amendementRefUid": f"AMANR5L17PO838901BTC2915P0D1N{amdt_n:06d}",
            "objet": objet}


SCRUTINS = [
    _s("VTANR5L17V7701", "7701", 62, 62, 32, 23, 39, 0, 1388, "amdt 1388"),
    _s("VTANR5L17V7706", "7706", 81, 81, 41, 27, 54, 0, 1136, "amdt 1136 Pollet"),
    _s("VTANR5L17V7709", "7709", 91, 91, 46, 33, 58, 0, 453, "amdt 453 Gruet"),
    _s("VTANR5L17V7718", "7718", 91, 91, 46, 33, 58, 0, 456, "amdt 456 Gruet"),
]

# ce que l'OCR lit sur l'écran-résultat du scrutin 7706
READING_7706 = {"votants": 81, "exprimes": 81, "majorite": 41,
                "pour": 27, "contre": 54, "abstentions": 0}
# le triplet ambigu (91,33,58) partagé par 7709 et 7718
READING_AMBIG = {"votants": 91, "exprimes": 91, "majorite": 46,
                 "pour": 33, "contre": 58, "abstentions": 0}


def test_unique_numbers_resolve_by_figures():
    m = rs.match_scrutin(READING_7706, SCRUTINS)
    assert m["scrutin"] == "VTANR5L17V7706"
    assert m["numero"] == "7706"
    assert m["method"] == "chiffres"


def test_partial_reading_still_matches():
    """Une case non lue (majorité/abstentions à None) n'empêche pas le match."""
    partial = {"votants": 81, "pour": 27, "contre": 54,
               "exprimes": None, "majorite": None, "abstentions": None}
    assert rs.match_scrutin(partial, SCRUTINS)["scrutin"] == "VTANR5L17V7706"


def test_tie_on_figures_is_none_without_amendment():
    assert rs.match_scrutin(READING_AMBIG, SCRUTINS) is None


def test_tie_broken_by_amendment_uid():
    uid = "AMANR5L17PO838901BTC2915P0D1N000456"
    m = rs.match_scrutin(READING_AMBIG, SCRUTINS, amendement_uid=uid)
    assert m["scrutin"] == "VTANR5L17V7718"
    assert m["method"] == "chiffres+amendement"


def test_absent_reading_resolves_to_none():
    assert rs.match_scrutin({"votants": 81, "pour": 99, "contre": 54}, SCRUTINS) is None


# --- ancrage sur la vraie séance complète (skip si la fixture du spike est absente) ---

_REAL = os.path.join(os.path.dirname(__file__), "..", "spikes",
                     "2026-07-03-scrutin-ocr", "fixtures",
                     "scrutins_seance_20260626.json")


def test_real_seance_81_27_54_is_scrutin_7706():
    if not os.path.exists(_REAL):
        pytest.skip("fixture séance réelle absente")
    scrutins = json.load(open(_REAL, encoding="utf-8"))
    m = rs.match_scrutin(READING_7706, scrutins)
    assert m is not None and m["numero"] == "7706" and m["method"] == "chiffres"
