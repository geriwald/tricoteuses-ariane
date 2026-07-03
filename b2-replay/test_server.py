"""Tests for B2's HTTP layer — the perfect mock of the real AN endpoints.

The causal routes (derouleur, Eliasse) serve exactly what B1 would poll live, gated
wall<=t. The derouleur route serves the raw bytes B3 captured, verbatim and with the
real content-type — B1 must not be able to tell replay from live (spec §B2). Some
raw payloads are not valid UTF-8, so bytes are served untouched.

`resolve_route(record, t_ms, path)` -> (status, content_type, body_bytes) is the pure
dispatch, tested without a socket.
"""
from replay import Record
import server


def _make_record(tmp_path):
    """A minimal on-disk record: one derouleur snapshot at +60s, a video anchor."""
    raw = tmp_path / "raw" / "derouleur"
    raw.mkdir(parents=True)
    # raw bytes include a non-UTF-8 byte to prove we serve verbatim
    (raw / "d1.json").write_bytes(b'{"racine":"\xe9live"}')
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", "raw_ref": {"derouleur": "d1.json"}, '
        '"changed": {"derouleur": true}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00\x00")
    return Record(str(tmp_path))


def test_derouleur_route_serves_raw_bytes_verbatim(tmp_path):
    rec = _make_record(tmp_path)
    # at +90s the +60s snapshot is visible
    status, ctype, body = server.resolve_route(rec, 90_000, "/local/derouleur/derouleur.json")
    assert status == 200
    assert ctype == "application/json"
    assert body == b'{"racine":"\xe9live"}'   # byte-exact, not re-encoded


def test_derouleur_route_is_causal_before_first_snapshot(tmp_path):
    rec = _make_record(tmp_path)
    # at t=0 the derouleur snapshot (+60s) has not happened yet → 404 (as if live: nothing)
    status, ctype, body = server.resolve_route(rec, 0, "/local/derouleur/derouleur.json")
    assert status == 404


def test_referential_route_is_not_gated(tmp_path):
    rec = _make_record(tmp_path)
    refdir = tmp_path / "referential"
    refdir.mkdir()
    (refdir / "acteurs.json").write_bytes(b'[{"uid":"PA1"}]')
    # even at t=0 the referential is served (out of the clock)
    status, ctype, body = server.resolve_route(rec, 0, "/referential/acteurs.json")
    assert status == 200
    assert ctype == "application/json"
    assert body == b'[{"uid":"PA1"}]'
