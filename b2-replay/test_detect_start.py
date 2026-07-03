"""Tests for the sitting-start detector (pure density logic).

The pre-sitting providéo is mostly silent with sparse announcements; the
sitting proper opens with DENSE speech (the chair reads the agenda). The
detector finds the first speech segment from which speech stays dense."""
import detect_start as ds


def test_sustained_speech_found_after_sparse_announcements():
    # sparse blips at 60s and 300s, then the sitting opens at 570s
    segs = [(60.0, 63.0), (300.0, 304.0),
            (570.0, 595.0), (598.0, 620.0), (624.0, 660.0)]
    t = ds.first_sustained_speech(segs, window=60.0, min_density=0.5)
    assert t == 570.0


def test_silence_only_returns_none():
    assert ds.first_sustained_speech([], 60.0, 0.5) is None
    # blips never dense enough
    assert ds.first_sustained_speech([(10.0, 12.0), (200.0, 203.0)], 60.0, 0.5) is None


def test_speech_from_the_start_returns_zero_ish():
    segs = [(2.0, 30.0), (31.0, 58.0), (60.0, 90.0)]
    assert ds.first_sustained_speech(segs, 60.0, 0.5) == 2.0


def test_record_reads_persisted_sitting_start(tmp_path):
    """B2 only READS sitting_start.json (one-shot data); absent → 0."""
    import json
    from replay import Record
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "hemi_20260701134502_1.mp4").write_text("")
    (tmp_path / "index.ndjson").write_text("")
    r = Record(str(tmp_path))
    assert r.sitting_start_ms() == 0
    (tmp_path / "sitting_start.json").write_text(
        json.dumps({"sitting_start_ms": 567000, "method": "vad-sustained-60s"}))
    assert r.sitting_start_ms() == 567000
