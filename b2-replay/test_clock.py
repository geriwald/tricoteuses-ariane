"""Tests for B2 ariane-replay — the causal replayer.

First contract, the one the whole brick exists to guarantee (spec §B2, decision 3):
at demo time `t`, a source snapshot is served ONLY if its wall-clock ≤ origin + t.
No future snapshot ever leaks. `t` is ms since the sitting's video start (the anchor,
verified 2026-07-01: mp4 filename stamp == liveplayer.nvs starttime == 2026-06-26
21:31:09 CEST). The gate is stateless w.r.t. `t` (re-filtered per request), so a
backward seek is trivial.
"""
from datetime import datetime, timezone, timedelta
import replay as r


CEST = timezone(timedelta(hours=2))
# the verified anchor for the 2026-06-26-evening record
ORIGIN = datetime(2026, 6, 26, 21, 31, 9, tzinfo=CEST)


def _tick(wall_iso, **extra):
    """A minimal index.ndjson record: only `wall` matters for the causal gate."""
    return {"wall": wall_iso, **extra}


def test_gate_serves_only_snapshots_at_or_before_t():
    # three ticks at +0s, +60s, +120s from origin
    index = [
        _tick("2026-06-26T21:31:09+02:00", tag="a"),
        _tick("2026-06-26T21:32:09+02:00", tag="b"),
        _tick("2026-06-26T21:33:09+02:00", tag="c"),
    ]
    # at t = 90s, only a (+0) and b (+60) are in the past; c (+120) is the future
    served = r.causal_snapshot(index, ORIGIN, t_ms=90_000)
    assert [s["tag"] for s in served] == ["a", "b"]


def test_no_future_snapshot_ever_leaks():
    index = [_tick("2026-06-26T21:33:09+02:00", tag="future")]
    # t = 0: nothing has happened yet relative to the video start
    assert r.causal_snapshot(index, ORIGIN, t_ms=0) == []


def test_exact_boundary_is_inclusive():
    # a snapshot whose wall == origin + t is available (≤, not <)
    index = [_tick("2026-06-26T21:32:09+02:00", tag="boundary")]
    served = r.causal_snapshot(index, ORIGIN, t_ms=60_000)
    assert [s["tag"] for s in served] == ["boundary"]


def test_naive_wall_is_read_as_paris_not_the_host_tz(monkeypatch):
    # record_sitting.py writes NAIVE wall stamps in Paris time (datetime.now()).
    # B2 must read them as Paris regardless of the host TZ, else the causal gate
    # drifts silently when B2 runs on a host that is not Europe/Paris (serenity).
    monkeypatch.setenv("TZ", "America/New_York")
    import time as _t
    _t.tzset()
    try:
        # naive stamp == origin + 60s in Paris; host is 6h behind
        index = [_tick("2026-06-26T21:32:09", tag="paris")]
        assert [s["tag"] for s in r.causal_snapshot(index, ORIGIN, t_ms=60_000)] == ["paris"]
        # one second earlier is still in the past
        assert [s["tag"] for s in r.causal_snapshot(index, ORIGIN, t_ms=59_000)] == []
    finally:
        monkeypatch.delenv("TZ", raising=False)
        _t.tzset()
