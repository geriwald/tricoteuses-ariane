"""Speaker-boundary detection over sliding segmentation windows (pure core).

pyannote/segmentation-3.0 yields per-frame activities for up to 3 LOCAL
speakers on a ~10s window; labels permute between windows, so identity cannot
cross windows — but a *switch* inside one window is a real boundary. The
detector finds the last dominant-speaker switch of a window (both sides long
enough to be a turn, silence tolerated in between) and dedupes the same
handover seen by successive overlapping windows with a flow-time cooldown.

Boundaries are anonymous: they say WHERE the turn changes, the name deduction
says WHO speaks (spec 2026-07-02, speech-deduced trame). The model inference
(GPU-free, CPU) lives in weaver_live; this module is pure and tested.
"""
import numpy as np

# a real speaking turn: at least this long on each side of the switch
MIN_TURN_S = 1.0


def _dominant_per_frame(acts, threshold=0.5):
    """Per-frame dominant speaker index, -1 for silence. acts: (frames, K)."""
    dom = acts.argmax(axis=1)
    dom[acts.max(axis=1) < threshold] = -1
    return dom


def _segments(dom, frames_per_s):
    """Contiguous (speaker, start_s, end_s) runs, silence (-1) dropped."""
    segs = []
    start = 0
    for i in range(1, len(dom) + 1):
        if i == len(dom) or dom[i] != dom[start]:
            if dom[start] != -1:
                segs.append((int(dom[start]), start / frames_per_s, i / frames_per_s))
            start = i
    return segs


class BoundaryDetector:
    def __init__(self, cooldown=3.0):
        self._cooldown = cooldown
        self._last_t = None  # flow time of the last emitted boundary

    def feed_window(self, acts, window_start, window_dur):
        """One segmentation window in, at most one boundary (flow seconds) out.

        acts: (frames, K) activity matrix for this window.
        Finds the LAST switch between two different speakers whose surrounding
        turns are both >= MIN_TURN_S (merging same-speaker runs across silence),
        then applies the cooldown against previously emitted boundaries."""
        frames_per_s = len(acts) / window_dur
        segs = _segments(_dominant_per_frame(np.asarray(acts)), frames_per_s)

        # merge same-speaker runs separated only by silence
        merged = []
        for spk, s0, s1 in segs:
            if merged and merged[-1][0] == spk:
                merged[-1] = (spk, merged[-1][1], s1)
            else:
                merged.append((spk, s0, s1))

        boundary = None
        for (a, a0, a1), (b, b0, b1) in zip(merged, merged[1:]):
            if a == b:
                continue
            if (a1 - a0) >= MIN_TURN_S and (b1 - b0) >= MIN_TURN_S:
                boundary = window_start + (a1 + b0) / 2  # switch inside the gap

        if boundary is None:
            return None
        if self._last_t is not None and boundary < self._last_t + self._cooldown:
            return None
        self._last_t = boundary
        return boundary
