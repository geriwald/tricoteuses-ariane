"""Tests for B1 the SSE broadcast layer (spec 2026-07-01, scope §4).

Pure layer, no HTTP socket (mirrors how b2-replay tests resolve_route directly).
A Broadcaster fans each woven node out to subscribers as an SSE `data:` frame; a
new subscriber first receives the backlog, then live nodes as they are published.
"""
import json
import weaver as w


def test_sse_frame_is_data_line_terminated_by_blank_line():
    frame = w.sse_frame({"seq": 7, "text": "bonjour"})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame[len("data: "):].strip())
    assert payload["seq"] == 7


def test_sse_frame_keeps_utf8():
    frame = w.sse_frame({"text": "déléguée"})
    assert "déléguée" in frame


def test_new_subscriber_gets_backlog_then_live():
    bc = w.Broadcaster()
    bc.publish({"seq": 0, "text": "avant"})   # published before anyone subscribes
    sub = bc.subscribe()                       # must replay the backlog
    bc.publish({"seq": 1, "text": "apres"})    # then live

    got = [next(sub), next(sub)]
    seqs = [json.loads(f[len("data: "):].strip())["seq"] for f in got]
    assert seqs == [0, 1]


def test_multiple_subscribers_each_get_live_node():
    bc = w.Broadcaster()
    a = bc.subscribe()
    b = bc.subscribe()
    bc.publish({"seq": 5, "text": "x"})
    for sub in (a, b):
        payload = json.loads(next(sub)[len("data: "):].strip())
        assert payload["seq"] == 5
