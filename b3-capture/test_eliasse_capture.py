"""Tests for the option-B Eliasse capture in record_sitting.py.

B2 (the causal replayer) must serve Eliasse byte-exact, the way it already serves
the dérouleur and the two NVS. That requires B3 to save the two Eliasse HTTP bodies
VERBATIM — `prochainADiscuter.do` (the live position pointer) and `amendement.do`
(the ~27-field amendment detail) — as two independent raw sources, each sha1-deduped
on its own. The old code kept only a 6-field summary, from which B2 could not
reconstruct the real shape.

Fixtures are real captured bodies (bibard 2934, numAmdt 1). Measured on two
consecutive live fetches: no volatile field, so plain sha1 dedup on the body is
enough — no canon_eliasse (unlike the dérouleur's extract_date_time).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_sitting as rs

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "testdata")


def _fixture(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


PROCHAIN = _fixture("eliasse_prochain_2934_1.json")
AMENDEMENT = _fixture("eliasse_amendement_2934_1.json")


def test_state_eliasse_parses_summary_from_raw_bodies():
    # the summary is now parsed from the two raw bodies (no network in the parser),
    # keeping the fields the console change-log needs
    s = rs.state_eliasse(PROCHAIN, AMENDEMENT)
    assert s["bibard"] == "2934"
    assert s["numAmdt"] == "1"
    assert s["organe"] == "AN"
    assert s["etat"] == "AC"
    assert s["place"] == "Article 2 bis"


def test_state_eliasse_tolerates_missing_amendement_body():
    # between amendments prochainADiscuter may point at a numAmdt whose detail is not
    # (yet) fetchable; the summary must still parse from the pointer alone
    s = rs.state_eliasse(PROCHAIN, None)
    assert s["bibard"] == "2934"
    assert s["numAmdt"] == "1"
    assert s["sort"] is None and s["etat"] is None and s["place"] is None


def test_two_independent_raw_sources_are_saved_byte_exact(tmp_path):
    # B3 must persist the two bodies VERBATIM under distinct source dirs, so B2 can
    # serve /eliasse/prochainADiscuter.do and /eliasse/amendement.do byte-for-byte
    saver = rs.RawSaver(str(tmp_path))
    ref_p, changed_p = saver.maybe_save("eliasse_prochain", "json", PROCHAIN, "130000_000")
    ref_a, changed_a = saver.maybe_save("eliasse_amendement", "json", AMENDEMENT, "130000_000")
    assert changed_p and changed_a
    with open(os.path.join(tmp_path, "raw", "eliasse_prochain", ref_p), "rb") as f:
        assert f.read() == PROCHAIN          # byte-exact, not a re-serialized summary
    with open(os.path.join(tmp_path, "raw", "eliasse_amendement", ref_a), "rb") as f:
        assert f.read() == AMENDEMENT


def test_dedup_is_independent_per_source(tmp_path):
    # unchanged body -> no new file (changed=False); each source dedups on its own
    saver = rs.RawSaver(str(tmp_path))
    saver.maybe_save("eliasse_prochain", "json", PROCHAIN, "130000_000")
    ref2, changed2 = saver.maybe_save("eliasse_prochain", "json", PROCHAIN, "130002_000")
    assert changed2 is False
    # a different amendment body on the OTHER source is a real change, saved fresh
    other = AMENDEMENT.replace(b'"numero":"1"', b'"numero":"2"')
    assert other != AMENDEMENT           # guard: the mutation actually changed a byte
    _, changed_a1 = saver.maybe_save("eliasse_amendement", "json", AMENDEMENT, "130000_000")
    _, changed_a2 = saver.maybe_save("eliasse_amendement", "json", other, "130004_000")
    assert changed_a1 and changed_a2
