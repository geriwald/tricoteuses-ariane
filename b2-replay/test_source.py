"""Tests for resolving the current raw snapshot of a source at demo time `t`.

For a perfect mock (spec §B2), B2 serves the *raw bytes* B3 captured — the most
recent snapshot whose wall ≤ t. `changed=false` ticks repeat the previous raw_ref,
so the resolver just walks the causal snapshot backwards for the last ref present.
Returns the raw_ref (a filename under raw/<source>/), never decoded content — the
bytes are served verbatim (some derouleur payloads are not even valid UTF-8).
"""
from datetime import datetime, timezone, timedelta
import replay as r

CEST = timezone(timedelta(hours=2))
ORIGIN = datetime(2026, 6, 26, 21, 31, 9, tzinfo=CEST)


def _tick(wall, refs):
    return {"wall": wall, "raw_ref": refs, "changed": {k: True for k in refs}}


def test_returns_ref_of_latest_tick_at_or_before_t():
    index = [
        _tick("2026-06-26T21:31:39", {"derouleur": "old.json"}),   # +30s
        _tick("2026-06-26T21:32:09", {"derouleur": "new.json"}),   # +60s
    ]
    # at +45s only the +30s tick is visible → old.json
    assert r.current_raw_ref(index, ORIGIN, 45_000, "derouleur") == "old.json"
    # at +75s the +60s tick is visible → new.json
    assert r.current_raw_ref(index, ORIGIN, 75_000, "derouleur") == "new.json"


def test_none_before_any_snapshot():
    index = [_tick("2026-06-26T21:32:09", {"derouleur": "new.json"})]
    # t=0: the first derouleur snapshot (+60s) has not happened yet
    assert r.current_raw_ref(index, ORIGIN, 0, "derouleur") is None


def test_carries_last_ref_across_unchanged_ticks():
    # a source that changed once then stayed: later ticks repeat its ref, but even
    # if a later tick omitted it, the resolver must still find the last real one.
    index = [
        _tick("2026-06-26T21:31:39", {"derouleur": "a.json", "eliasse": "e1.json"}),
        {"wall": "2026-06-26T21:33:09", "raw_ref": {"eliasse": "e2.json"},
         "changed": {"eliasse": True}},   # derouleur absent from this tick
    ]
    # at +120s, derouleur's last known ref is still a.json
    assert r.current_raw_ref(index, ORIGIN, 120_000, "derouleur") == "a.json"
    assert r.current_raw_ref(index, ORIGIN, 120_000, "eliasse") == "e2.json"
