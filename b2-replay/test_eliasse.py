"""Tests for B2's Eliasse routes — the second causal source (spec §B2, option A).

record_sitting.py saved a self-made SUMMARY {bibard,numAmdt,organe,etat,place,sort},
not the raw prochainADiscuter.do / amendement.do responses (that raw capture is
option B, noted for later). So B2 reconstructs both .do responses into their real
shape from the summary — faithful on the fields B1 reads (numAmdt, sortEnSeance,
etat, placeReference), best-effort on the rest (author/dispositif are absent from
the summary; B1 takes the registered author from the dérouleur, not Eliasse).

Both routes are causal: gated wall<=t, 404 before the first Eliasse snapshot.
"""
from replay import Record
import server


def _make_record(tmp_path, summary):
    import json
    raw = tmp_path / "raw" / "eliasse"
    raw.mkdir(parents=True)
    (raw / "e1.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", "raw_ref": {"eliasse": "e1.json"}, '
        '"changed": {"eliasse": true}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00")
    return Record(str(tmp_path))


SUMMARY = {"bibard": "2915", "numAmdt": "99", "organe": "AN",
           "etat": "AC", "place": "Article 6", "sort": "Rejeté"}


def test_prochain_a_discuter_reconstructs_real_shape(tmp_path):
    import json
    rec = _make_record(tmp_path, SUMMARY)
    status, ctype, body = server.resolve_route(
        rec, 90_000, "/eliasse/prochainADiscuter.do")
    assert status == 200 and ctype == "application/json"
    d = json.loads(body)
    p = d["prochainADiscuter"]
    assert p["bibard"] == "2915"
    assert p["numAmdt"] == "99"
    assert p["organeAbrv"] == "AN"       # organe → organeAbrv (real field name)
    assert p["legislature"] == "17"


def test_amendement_reconstructs_fields_b1_reads(tmp_path):
    import json
    rec = _make_record(tmp_path, SUMMARY)
    status, ctype, body = server.resolve_route(rec, 90_000, "/eliasse/amendement.do")
    assert status == 200
    a = json.loads(body)["amendements"][0]
    assert a["sortEnSeance"] == "Rejeté"     # sort → sortEnSeance
    assert a["etat"] == "AC"
    assert a["placeReference"] == "Article 6"  # place → placeReference
    assert a["numero"] == "99"


def test_eliasse_routes_are_causal(tmp_path):
    rec = _make_record(tmp_path, SUMMARY)
    # t=0: the Eliasse snapshot (+60s) has not happened yet
    assert server.resolve_route(rec, 0, "/eliasse/prochainADiscuter.do")[0] == 404
    assert server.resolve_route(rec, 0, "/eliasse/amendement.do")[0] == 404


# ---- new bundle format (option B): the two .do bodies saved VERBATIM ----------
# B3 now stores prochainADiscuter.do / amendement.do byte-exact under
# raw/eliasse_prochain / raw/eliasse_amendement (no raw/eliasse summary). B2 must
# serve those bytes untouched, gated wall<=t, with no reconstruction in the middle.

PROCHAIN_BYTES = b'{"prochainADiscuter":{"bibard":"2915","numAmdt":"99"}}'
AMENDEMENT_BYTES = b'{"amendements":[{"numero":"99","sortEnSeance":"Rejete"}]}'


def _make_split_record(tmp_path, prochain, amendement):
    for source, body in (("eliasse_prochain", prochain),
                         ("eliasse_amendement", amendement)):
        raw = tmp_path / "raw" / source
        raw.mkdir(parents=True)
        (raw / "e1.json").write_bytes(body)
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", "raw_ref": '
        '{"eliasse_prochain": "e1.json", "eliasse_amendement": "e1.json"}, '
        '"changed": {"eliasse_prochain": true, "eliasse_amendement": true}}\n',
        encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00")
    return Record(str(tmp_path))


def test_split_format_serves_verbatim_bytes(tmp_path):
    rec = _make_split_record(tmp_path, PROCHAIN_BYTES, AMENDEMENT_BYTES)
    status, ctype, body = server.resolve_route(
        rec, 90_000, "/eliasse/prochainADiscuter.do")
    assert status == 200 and ctype == "application/json"
    assert body == PROCHAIN_BYTES               # verbatim, not reconstructed
    status, ctype, body = server.resolve_route(rec, 90_000, "/eliasse/amendement.do")
    assert status == 200 and ctype == "application/json"
    assert body == AMENDEMENT_BYTES


def test_split_format_routes_are_causal(tmp_path):
    rec = _make_split_record(tmp_path, PROCHAIN_BYTES, AMENDEMENT_BYTES)
    # t=0: the verbatim snapshot (+60s) has not appeared yet
    assert server.resolve_route(rec, 0, "/eliasse/prochainADiscuter.do")[0] == 404
    assert server.resolve_route(rec, 0, "/eliasse/amendement.do")[0] == 404


def test_split_format_missing_amendement_is_404(tmp_path):
    # amendement.do may legitimately be absent on a tick (B3 saves it only when the
    # live returned one); prochain still serves, amendement 404s — no reconstruction.
    raw = tmp_path / "raw" / "eliasse_prochain"
    raw.mkdir(parents=True)
    (raw / "e1.json").write_bytes(PROCHAIN_BYTES)
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", '
        '"raw_ref": {"eliasse_prochain": "e1.json"}, '
        '"changed": {"eliasse_prochain": true}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00")
    rec = Record(str(tmp_path))
    assert server.resolve_route(rec, 90_000, "/eliasse/prochainADiscuter.do")[0] == 200
    assert server.resolve_route(rec, 90_000, "/eliasse/amendement.do")[0] == 404
