"""Tests for loading a real B3 record into B2 (spec §B2).

Two pure pieces: resolving the clock origin (t=0) from the mp4 filename stamp
(verified anchor, 2026-07-01: it equals liveplayer.nvs starttime), and parsing
index.ndjson into a list of tick dicts. The raw response for each source lives in
raw/<source>/<raw_ref>; the index only carries the pointer.
"""
from datetime import datetime, timezone, timedelta
import replay as r

PARIS = timezone(timedelta(hours=2))  # CEST for June


def test_origin_from_video_filename_stamp():
    # hemi_<YYYYMMDDHHMMSS>_1.mp4 → the sitting's video start, in Paris time
    origin = r.origin_from_video("hemi_20260626213109_1.mp4")
    assert origin == datetime(2026, 6, 26, 21, 31, 9, tzinfo=PARIS)


def test_origin_matches_liveplayer_starttime_epoch():
    # the two anchors are the same instant (this is the whole point of the anchor)
    origin = r.origin_from_video("hemi_20260626213109_1.mp4")
    assert int(origin.timestamp()) == 1782502269


def test_load_index_parses_every_tick(tmp_path):
    idx = tmp_path / "index.ndjson"
    idx.write_text(
        '{"wall": "2026-06-26T21:33:08.628", "raw_ref": {"derouleur": "a.json"}, "changed": {"derouleur": true}}\n'
        '{"wall": "2026-06-26T21:33:10.936", "raw_ref": {"derouleur": "a.json"}, "changed": {"derouleur": false}}\n',
        encoding="utf-8")
    ticks = r.load_index(str(idx))
    assert len(ticks) == 2
    assert ticks[0]["wall"] == "2026-06-26T21:33:08.628"
    assert ticks[1]["raw_ref"]["derouleur"] == "a.json"


def test_load_index_skips_blank_lines(tmp_path):
    idx = tmp_path / "index.ndjson"
    idx.write_text(
        '{"wall": "2026-06-26T21:33:08.628", "raw_ref": {}, "changed": {}}\n'
        '\n',
        encoding="utf-8")
    assert len(r.load_index(str(idx))) == 1
