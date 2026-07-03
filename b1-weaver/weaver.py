"""B1 ariane-weaver — the weaving core.

Turns raw Whisper streaming events into `thread.ndjson` nodes (spec archi
§"Thread event format"). Pure and GPU-free: the streaming/ffmpeg plumbing lives
elsewhere and only feeds this core dicts of shape
    {"type": "interim"|"utterance", "beg": float, "end": float?, "text": str}
where beg/end are seconds relative to the flow's t=0.

Two-pass model (D5): an `interim` is a provisional node; the confirmed `utterance`
supersedes the last provisional as consolidated. Stamping (D3): t = beg*1000 ms
(relative to the flow's t=0). No absolute wall-clock — not knowable in live.
"""
import json
import queue
import threading


def sse_frame(node):
    """One Server-Sent-Events frame: a `data:` line + the blank-line terminator."""
    return "data: " + json.dumps(node, ensure_ascii=False) + "\n\n"


class Seq:
    """One strictly-increasing `seq` shared by every weaver of the thread (STT +
    trame), so their nodes interleave into a single append-only sequence.
    Thread-safe: the Whisper loop and the derouleur poller emit concurrently."""

    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            n = self._n
            self._n += 1
            return n


class Broadcaster:
    """Fans each woven node out to SSE subscribers. Thread-safe: the Whisper thread
    publishes, each subscriber (an HTTP handler thread) consumes its own queue. A
    new subscriber first replays the backlog, then blocks for live nodes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._backlog = []
        self._subscribers = []  # list of queue.Queue

    def publish(self, node):
        with self._lock:
            self._backlog.append(node)
            subs = list(self._subscribers)
        for q in subs:
            q.put(node)

    def subscribe(self):
        """Yield SSE frames: the backlog first, then live nodes as they arrive."""
        q = queue.Queue()
        with self._lock:
            backlog = list(self._backlog)
            self._subscribers.append(q)
        for node in backlog:
            yield sse_frame(node)
        while True:
            node = q.get()
            yield sse_frame(node)


class ThreadLog:
    """Append-only persistence of woven nodes to `thread.ndjson`, one JSON line
    each. Keeps the backlog in memory so a late SSE subscriber can replay it."""

    def __init__(self, path):
        self.path = path
        self._nodes = []
        self._fh = open(path, "a", encoding="utf-8")

    def append(self, node):
        self._nodes.append(node)
        self._fh.write(json.dumps(node, ensure_ascii=False) + "\n")
        self._fh.flush()

    def history(self):
        return list(self._nodes)

    def close(self):
        self._fh.close()


class Weaver:
    def __init__(self, seq=None):
        self._seq = seq or Seq()
        self._pending_provisional = None  # seq of the last un-consolidated interim

    def feed(self, event):
        """Consume one raw Whisper event, return the list of nodes it produces.

        The only timestamp is `t` = ms since the flow's t=0 (relative). That is all
        the weave needs; an absolute wall-clock is not knowable in live and was
        dropped as pure confusion."""
        node = {
            "t": int(event["beg"] * 1000),
            "seq": self._seq.next(),
            "kind": "utterance",
            "state": "provisional" if event["type"] == "interim" else "consolidated",
            "text": event["text"],
            "source": "stt",
        }

        # every step of a chain replaces its predecessor: interim rewrites
        # interim, and the confirmed utterance closes the chain
        if self._pending_provisional is not None:
            node["supersedes"] = self._pending_provisional
        self._pending_provisional = node["seq"] if event["type"] == "interim" else None

        return [node]
