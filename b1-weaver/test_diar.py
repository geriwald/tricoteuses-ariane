"""Tests for the speaker-boundary detector (diarization core, pure part).

pyannote/segmentation-3.0 runs on sliding 10s windows and yields per-frame
speaker activities with LOCAL labels (they permute between windows). The pure
detector finds a dominant-speaker switch inside one window and dedupes across
overlapping windows by a flow-time cooldown. Patterns below mirror the real
matrices observed on the 26/06 double handover (ministre→présidente→Hetzel).
"""
import numpy as np

import diar


def acts(*spans):
    """Build a (frames, 3) activity matrix from (speaker, seconds) spans,
    10 frames per second; speaker None = silence."""
    rows = []
    for spk, secs in spans:
        for _ in range(int(secs * 10)):
            row = [0.0, 0.0, 0.0]
            if spk is not None:
                row[spk] = 1.0
            rows.append(row)
    return np.array(rows, dtype=np.float32)


def test_switch_inside_window_is_found():
    """ministre (spk1) 8s then présidente (spk2) 2s → boundary at ~8s."""
    d = diar.BoundaryDetector()
    m = acts((1, 8.0), (2, 2.0))
    t = d.feed_window(m, window_start=100.0, window_dur=10.0)
    assert t is not None and 107.0 <= t <= 109.0


def test_single_speaker_window_yields_nothing():
    d = diar.BoundaryDetector()
    assert d.feed_window(acts((1, 10.0)), 100.0, 10.0) is None


def test_silence_gap_does_not_fake_a_boundary():
    """Same speaker around a silence: no switch."""
    d = diar.BoundaryDetector()
    m = acts((1, 4.0), (None, 2.0), (1, 4.0))
    assert d.feed_window(m, 100.0, 10.0) is None


def test_switch_across_silence_is_found():
    """présidente 3s, silence 1s, Hetzel 6s (real +8s window pattern)."""
    d = diar.BoundaryDetector()
    m = acts((2, 3.0), (None, 1.0), (1, 6.0))
    t = d.feed_window(m, 1876.0, 10.0)
    assert t is not None and 1879.0 <= t <= 1881.0


def test_overlapping_windows_dedupe_by_cooldown():
    """The same handover seen by consecutive sliding windows emits ONCE."""
    d = diar.BoundaryDetector(cooldown=3.0)
    t1 = d.feed_window(acts((1, 8.0), (2, 2.0)), 100.0, 10.0)   # boundary ~108
    assert t1 is not None
    # slid by 2s: same boundary now at ~6s inside the window
    t2 = d.feed_window(acts((1, 6.0), (2, 4.0)), 102.0, 10.0)
    assert t2 is None
    # a genuinely later switch (beyond cooldown) is emitted
    t3 = d.feed_window(acts((2, 4.0), (0, 6.0)), 108.0, 10.0)
    assert t3 is not None and t3 > t1 + 3.0


def test_too_short_segments_are_ignored():
    """A sub-second blip is not a speaker turn."""
    d = diar.BoundaryDetector()
    m = acts((1, 9.4), (2, 0.6))
    assert d.feed_window(m, 100.0, 10.0) is None
