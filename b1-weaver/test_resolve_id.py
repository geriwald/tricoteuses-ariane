"""Tests for the canonical ID resolver (spec 2026-07-01-canonical-id-resolution).

Detected name (noisy, STT-side) -> canonical uid (PA<tribun>), matched against the
sitting's actor set. Never a silent false positive: title-only / absent / ambiguous
surname -> None (TDC03, honesty over a wrong ID).
"""
import resolve_id as r


ACTORS = [
    {"uid": "PA266797", "civ": "M.", "prenom": "Philippe", "nom": "Gosselin"},
    {"uid": "PA342384", "civ": "Mme", "prenom": "Élisa", "nom": "Martin"},
    {"uid": "PA607619", "civ": "M.", "prenom": "Paul", "nom": "Molac"},
    {"uid": "PA000001", "civ": "M.", "prenom": "Jean", "nom": "Martin"},  # 2nd Martin -> ambiguity
]


def test_exact_full_name_with_civility():
    """Civility stripped, exact name -> the uid."""
    res = r.resolve("Monsieur Philippe Gosselin", ACTORS)
    assert res is not None and res["uid"] == "PA266797"


def test_accent_and_case_insensitive_and_disambiguated_by_first_name():
    """'elisa martin' (lowercased, no accent) picks the right Martin via first name."""
    res = r.resolve("elisa martin", ACTORS)
    assert res is not None and res["uid"] == "PA342384"


def test_unique_surname_resolves():
    res = r.resolve("Molac", ACTORS)
    assert res is not None and res["uid"] == "PA607619"


def test_phonetic_error_on_surname_still_resolves():
    """A light STT error on the surname still resolves (fuzzy)."""
    res = r.resolve("Philippe Gosselan", ACTORS)
    assert res is not None and res["uid"] == "PA266797"


def test_title_only_returns_none():
    assert r.resolve("Monsieur le Président", ACTORS) is None


def test_absent_name_returns_none():
    assert r.resolve("Jacques Inconnu", ACTORS) is None


def test_ambiguous_surname_returns_none():
    """'Martin' alone matches two actors -> refuse rather than guess."""
    assert r.resolve("Martin", ACTORS) is None


def test_surname_with_clear_best_beats_a_distant_second():
    """Real 26/06 case: STT «Bruet» scores Gruet 0.800 and Barbut 0.727 — both
    over the threshold, but not «too close» (spec D3): the clear best wins.
    Refusal is for genuine ties, not for any second hit above the floor."""
    actors = ACTORS + [
        {"uid": "PA794058", "civ": "Mme", "prenom": "Justine", "nom": "Gruet"},
        {"uid": "PA873625", "civ": "M.", "prenom": "Léo", "nom": "Barbut"},
    ]
    res = r.resolve("madame Bruet", actors)
    assert res is not None and res["uid"] == "PA794058"
