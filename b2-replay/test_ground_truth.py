"""Tests for B2's ground-truth NVS route (spec §B2, non-causal).

The post-production NVS (ground-truth-vod/data.nvs, status=vod, effective speakers)
is served WHOLE, out of the clock, for B4's comparison pane — deliberately not causal
(it is what Ariane automates, an output to compare against, never a B1 input). Served
verbatim as text/xml, at any t (even 0). Not on an AN-mirror path: B1 never polls it
as live; it is a dedicated B4 feed.
"""
from replay import Record
import server


def _make_record(tmp_path):
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", "raw_ref": {}, "changed": {}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00")
    gt = tmp_path / "ground-truth-vod"
    gt.mkdir()
    (gt / "data.nvs").write_bytes(b'<?xml version="1.0"?><data status="vod"/>')
    return Record(str(tmp_path))


def test_ground_truth_nvs_served_whole_at_any_t(tmp_path):
    rec = _make_record(tmp_path)
    # even at t=0 (non-causal): the full post-prod NVS is available
    status, ctype, body = server.resolve_route(rec, 0, "/ground-truth/data.nvs")
    assert status == 200
    assert ctype == "text/xml"
    assert body == b'<?xml version="1.0"?><data status="vod"/>'


def test_ground_truth_missing_is_404(tmp_path):
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-26T21:32:09", "raw_ref": {}, "changed": {}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260626213109_1.mp4").write_bytes(b"\x00")
    rec = Record(str(tmp_path))
    assert server.resolve_route(rec, 0, "/ground-truth/data.nvs")[0] == 404
