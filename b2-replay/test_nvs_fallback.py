"""Record.nvs_timeline() must fall back to the live-captured NVS when the record has
no ground-truth-vod/ dir.

Some records (e.g. 2026-06-30-soir) were never given a ground-truth-vod/ pull, but
their raw/data_nvs + raw/liveplayer hold the NVS (richer, even). B2 uses the LAST
captured snapshot of each (the most complete, post-prod NVS keeps filling in). The
join is the same nvs_timeline(); only the source of the two XML blobs differs.
"""
from replay import Record


def _base_record(tmp_path):
    (tmp_path / "index.ndjson").write_text(
        '{"wall": "2026-06-30T20:52:00", "raw_ref": {}, "changed": {}}\n', encoding="utf-8")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260630205107_1.mp4").write_bytes(b"\x00")
    return tmp_path


DATA = b"""<?xml version="1.0"?><data status="vod">
  <speakers><speaker id="S1"><name>Mme Perrine Goulet</name></speaker></speakers>
  <chapters><chapter id="C1" label="Mme Perrine Goulet"><speaker id="S1"/></chapter></chapters>
</data>"""
LP = b"""<?xml version="1.0"?><player starttime="1782845467">
  <synchro id="C1" timecode="561000"/></player>"""


def test_uses_ground_truth_when_present(tmp_path):
    _base_record(tmp_path)
    gt = tmp_path / "ground-truth-vod"; gt.mkdir()
    (gt / "data.nvs").write_bytes(DATA)
    (gt / "liveplayer.nvs").write_bytes(LP)
    tl = Record(str(tmp_path)).nvs_timeline()
    assert [e["speaker"] for e in tl] == ["Mme Perrine Goulet"]


def test_falls_back_to_last_raw_snapshot(tmp_path):
    _base_record(tmp_path)
    # no ground-truth-vod/ ; the NVS lives in raw/, two snapshots — use the LAST
    for src, blob in (("data_nvs", DATA), ("liveplayer", LP)):
        d = tmp_path / "raw" / src; d.mkdir(parents=True)
        (d / "205200_000.nvs").write_bytes(b"<data/>" if src == "data_nvs" else b"<player/>")
        (d / "205900_000.nvs").write_bytes(blob)  # later snapshot = the complete one
    tl = Record(str(tmp_path)).nvs_timeline()
    assert [e["speaker"] for e in tl] == ["Mme Perrine Goulet"]
    assert tl[0]["t_ms"] == 561000


def test_none_when_no_nvs_anywhere(tmp_path):
    _base_record(tmp_path)
    assert Record(str(tmp_path)).nvs_timeline() is None
