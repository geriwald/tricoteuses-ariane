"""Tests for the B2 live streamer plumbing (no ffmpeg: the pure/IO-light parts)."""
import os

import stream


def test_file_whitelist_blocks_traversal(tmp_path):
    s = stream.LiveStreamer("/dev/null")
    with open(os.path.join(s._dir, "stream.m3u8"), "w") as f:
        f.write("#EXTM3U")
    assert s.file("stream.m3u8") == b"#EXTM3U"
    assert s.file("seg_00042.ts") is None          # whitelisted shape, absent file
    assert s.file("../../etc/passwd") is None      # traversal blocked
    assert s.file("stream.m3u8/../x") is None
    assert s.file("evil.ts") is None


def test_set_video_stops_and_repoints(tmp_path):
    s = stream.LiveStreamer("/a.mp4")
    s.set_video("/b.mp4")
    assert s._video == "/b.mp4" and s._proc is None


def test_list_records_filters_replayable(tmp_path):
    ok = tmp_path / "2026-07-01-aprem"
    (ok / "video").mkdir(parents=True)
    (ok / "index.ndjson").write_text("")
    (ok / "video" / "hemi_20260701134502_1.mp4").write_text("")
    no_video = tmp_path / "2026-07-02-soir"
    no_video.mkdir()
    (no_video / "index.ndjson").write_text("")
    (tmp_path / "cron.log").write_text("")  # not a dir

    recs = stream.list_records(str(tmp_path), current="2026-07-01-aprem")
    assert recs == [{"name": "2026-07-01-aprem", "current": True}]


def test_safe_record_name():
    assert stream.safe_record_name("2026-07-01-aprem") == "2026-07-01-aprem"
    assert stream.safe_record_name("../etc") is None
    assert stream.safe_record_name("a/b") is None
    assert stream.safe_record_name("") is None
