"""Tests for B1 the append-only thread log (spec 2026-07-01, scope §3).

The log persists each woven node as one JSON line to `thread.ndjson`, append-only,
and lets late subscribers replay what was already written. GPU-free.
"""
import json
import weaver as w


def test_append_writes_one_json_line_per_node(tmp_path):
    path = tmp_path / "thread.ndjson"
    log = w.ThreadLog(path)
    log.append({"seq": 0, "kind": "utterance", "text": "un"})
    log.append({"seq": 1, "kind": "utterance", "text": "deux"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["text"] == "un"
    assert json.loads(lines[1])["seq"] == 1


def test_append_is_utf8_not_escaped(tmp_path):
    """French text must be written as-is, not \\uXXXX (ensure_ascii=False)."""
    path = tmp_path / "thread.ndjson"
    log = w.ThreadLog(path)
    log.append({"seq": 0, "text": "La ministre déléguée à l'égalité."})
    assert "déléguée à l'égalité" in path.read_text(encoding="utf-8")


def test_history_returns_all_appended_nodes(tmp_path):
    """A late SSE subscriber replays the backlog via history()."""
    path = tmp_path / "thread.ndjson"
    log = w.ThreadLog(path)
    log.append({"seq": 0, "text": "un"})
    log.append({"seq": 1, "text": "deux"})
    assert [n["seq"] for n in log.history()] == [0, 1]
