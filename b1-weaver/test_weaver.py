"""Tests for B1 ariane-weaver — the weaving core (spec 2026-07-01-b1-weaver-design).

The core is pure and GPU-free: it turns raw Whisper streaming events
({type: interim|utterance, beg, end, text}) into `thread.ndjson` nodes. The only
timestamp is `t` = ms since the flow's t=0 (relative, all the weave needs). The
two-pass model (D5): an interim is a `provisional` node; the confirmed utterance
`supersedes` it as `consolidated`. Format contract: spec archi §"Thread event format".
"""
import weaver as w


def test_utterance_stamps_relative_t():
    """t = beg*1000 (ms since the flow's t=0). An utterance is consolidated."""
    weaver = w.Weaver()
    (node,) = weaver.feed({"type": "utterance", "beg": 12.5, "end": 15.0,
                           "text": "La parole est à Madame la ministre."})

    assert node["kind"] == "utterance"
    assert node["source"] == "stt"
    assert node["state"] == "consolidated"
    assert node["t"] == 12500
    assert "wall" not in node
    assert node["text"] == "La parole est à Madame la ministre."
    assert node["seq"] == 0


def test_interim_is_provisional():
    """D5: an interim (unconfirmed) is a provisional node."""
    weaver = w.Weaver()
    (node,) = weaver.feed({"type": "interim", "beg": 3.0, "text": "La parole"})

    assert node["state"] == "provisional"
    assert node["kind"] == "utterance"
    assert node["text"] == "La parole"


def test_seq_is_monotonic():
    """Each emitted node gets the next seq, append-only."""
    weaver = w.Weaver()
    (a,) = weaver.feed({"type": "interim", "beg": 1.0, "text": "un"})
    (b,) = weaver.feed({"type": "utterance", "beg": 1.0, "end": 2.0, "text": "un deux"})
    assert a["seq"] == 0
    assert b["seq"] == 1


def test_utterance_supersedes_the_pending_provisional():
    """D5: the confirmed utterance replaces the last provisional (supersedes)."""
    weaver = w.Weaver()
    (prov,) = weaver.feed({"type": "interim", "beg": 5.0, "text": "La parole est"})
    (cons,) = weaver.feed({"type": "utterance", "beg": 5.0, "end": 7.0,
                           "text": "La parole est à la ministre."})

    assert prov["state"] == "provisional"
    assert cons["state"] == "consolidated"
    assert cons["supersedes"] == prov["seq"]


def test_successive_interims_supersede_each_other():
    """Each interim REWRITES the previous one and must supersede it — otherwise
    intermediate provisionals stay orphaned forever in the thread (real case:
    684/685/686 never superseded, only 687 was, by the confirmed 688)."""
    weaver = w.Weaver()
    (a,) = weaver.feed({"type": "interim", "beg": 1.0, "text": "La"})
    (b,) = weaver.feed({"type": "interim", "beg": 1.0, "text": "La parole"})
    (c,) = weaver.feed({"type": "interim", "beg": 1.0, "text": "La parole est"})
    (d,) = weaver.feed({"type": "utterance", "beg": 1.0, "end": 2.0,
                        "text": "La parole est à la ministre."})

    assert "supersedes" not in a           # first of its chain
    assert b["supersedes"] == a["seq"]     # each rewrite replaces its predecessor
    assert c["supersedes"] == b["seq"]
    assert d["supersedes"] == c["seq"]     # the confirmation closes the chain

    # a fresh interim after the confirmation starts a NEW chain
    (e,) = weaver.feed({"type": "interim", "beg": 2.0, "text": "Merci"})
    assert "supersedes" not in e
