#!/usr/bin/env python3
"""B2 `ariane-replay` — causal replayer of a recorded AN sitting.

Replays a record produced by B3 (`record_sitting.py`: `index.ndjson` + `raw/` +
`video/` + `referential/`) under a single master clock, enforcing causality: at
demo time `t`, a source snapshot is served ONLY if its wall-clock ≤ origin + t, so
B1 (the weaver) cannot tell replay from live (spec §B2, decision 3).

`t` is milliseconds since the sitting's video start. The origin is the anchor
carried, identically, by the mp4 filename stamp and `liveplayer.nvs starttime`
(verified 2026-07-01). The master clock owns `t`; the video is its slave, never the
reverse (decision 7).

This module holds the pure, clock-independent core (the causal gate); the HTTP
server and the running clock build on top.
"""
import glob
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

# record_sitting.py stamps `wall` with a naive datetime.now() in Paris time. B2 may
# run on a host in another timezone (serenity), so a naive stamp must be pinned to
# Paris explicitly — never left to the host's local tz, or the causal gate drifts.
PARIS = ZoneInfo("Europe/Paris")


def _wall_ms(wall_iso):
    """Epoch-ms of a record's `wall`. Naive stamps are read as Paris (see PARIS)."""
    dt = datetime.fromisoformat(wall_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS)
    return dt.timestamp() * 1000


class MasterClock:
    """The single authority that owns `t` (ms since video start), spec §B2.

    Advances at real-time rate while playing, frozen while paused. The UI drives it
    by transport commands only (`play/pause/seek/seek_by`), never by pushing `t`.
    The video is slaved to it (clock → video), never the reverse (decision 7).

    Time is injected (`now()` → epoch seconds) so it is testable without sleeping and
    so the running server can use `time.monotonic` — a clock that cannot jump back.
    """

    def __init__(self, now=time.monotonic):
        self._now = now
        self.playing = False
        self._base_t = 0.0        # `t` (seconds) at the last play/pause/seek
        self._base_wall = None    # wall instant of that anchor (only while playing)

    def t_ms(self):
        t = self._base_t
        if self.playing:
            t += self._now() - self._base_wall
        return int(t * 1000)

    def _reanchor(self, t_seconds):
        self._base_t = max(0.0, t_seconds)
        self._base_wall = self._now()

    def play(self):
        if not self.playing:
            self._reanchor(self._base_t)
            self.playing = True

    def pause(self):
        if self.playing:
            self._base_t = self.t_ms() / 1000
            self.playing = False

    def seek(self, t_ms):
        self._reanchor(t_ms / 1000)

    def seek_by(self, delta_ms):
        self._reanchor(self.t_ms() / 1000 + delta_ms / 1000)


_VIDEO_STAMP = re.compile(r"_(\d{14})_")


def origin_from_video(filename):
    """The clock origin (t=0) from an AN VOD filename `hemi_<YYYYMMDDHHMMSS>_1.mp4`.

    The 14-digit stamp is the sitting's video start in Paris time; it equals the
    `liveplayer.nvs starttime` epoch (the verified anchor, 2026-07-01).
    """
    m = _VIDEO_STAMP.search(filename)
    if not m:
        raise ValueError(f"no 14-digit start stamp in video filename: {filename!r}")
    return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=PARIS)


def load_index(path):
    """Parse a B3 `index.ndjson` into a list of tick dicts (blank lines skipped)."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def nvs_timeline(data_nvs, liveplayer_nvs):
    """The ground-truth NVS chapters placed on the video timeline, sorted by t.

    Joins data.nvs (chapter tree + speakers) with liveplayer.nvs: a <synchro
    id=chapterId timecode=ms> whose id matches a chapter id places that chapter at
    `timecode` ms. Periodic 60s synchros (no matching chapter) are dropped. Each
    entry is {t_ms, label, speaker} — the comparison ground truth for B4's pane.
    """
    data = ET.fromstring(data_nvs)
    speakers_el = data.find("speakers")
    speakers = {s.attrib.get("id"): (s.findtext("name") or "").strip()
                for s in (speakers_el if speakers_el is not None else [])}
    chapters = {}
    for c in data.iter("chapter"):
        sp = c.find("speaker")
        spid = sp.attrib.get("id") if sp is not None else None
        chapters[c.attrib.get("id")] = ((c.attrib.get("label") or "").strip(),
                                        speakers.get(spid) or None if spid else None)

    lp = ET.fromstring(liveplayer_nvs)
    out = []
    for syn in lp.findall(".//synchro"):
        cid = syn.attrib.get("id")
        if cid in chapters:
            label, speaker = chapters[cid]
            out.append({"t_ms": int(syn.attrib.get("timecode")),
                        "label": label, "speaker": speaker})
    out.sort(key=lambda e: e["t_ms"])
    return out


def nvs_tree(data_nvs, liveplayer_nvs):
    """The NVS chapters as a tree, in document order, each node carrying its nesting
    and its timeline position. B4 shows the tree and bolds the ancestor chain of the
    last reached chapter, so the nesting must be preserved (unlike nvs_timeline).

    Each node: {id, parent, depth, label, speaker, t_ms}. `t_ms` is the synchro
    timecode (ms) when the chapter is placed on the video timeline, else None (in the
    tree, but never becomes current). Join is by chapter id, same as nvs_timeline.
    """
    data = ET.fromstring(data_nvs)
    speakers_el = data.find("speakers")
    speakers = {s.attrib.get("id"): (s.findtext("name") or "").strip()
                for s in (speakers_el if speakers_el is not None else [])}
    lp = ET.fromstring(liveplayer_nvs)
    tc = {syn.attrib.get("id"): int(syn.attrib.get("timecode"))
          for syn in lp.findall(".//synchro")}

    nodes = []

    def walk(parent_el, parent_id, depth):
        for c in parent_el:
            if c.tag != "chapter":
                continue
            cid = c.attrib.get("id")
            sp = c.find("speaker")
            spid = sp.attrib.get("id") if sp is not None else None
            nodes.append({
                "id": cid, "parent": parent_id, "depth": depth,
                "label": (c.attrib.get("label") or "").strip(),
                "speaker": (speakers.get(spid) or None) if spid else None,
                "t_ms": tc.get(cid),
            })
            walk(c, cid, depth + 1)

    chapters = data.find("chapters")
    if chapters is not None:
        walk(chapters, None, 0)
    return nodes


def causal_snapshot(index, origin, t_ms):
    """The records from `index` visible at demo time `t_ms` (ms since `origin`).

    A record is visible iff its `wall` is ≤ origin + t_ms. Stateless w.r.t. `t`:
    re-filtered on every call, so any `t` — including a smaller one after a
    backward seek — is served correctly.
    """
    cutoff = origin.timestamp() * 1000 + t_ms
    return [rec for rec in index if _wall_ms(rec["wall"]) <= cutoff]


class Record:
    """A B3 capture bundle on disk: the index, the clock origin, and byte access to
    the raw source snapshots and the frozen referential (spec §B2).

    Loaded once; the causal gate is re-applied per request against `origin`.
    """

    def __init__(self, path):
        self.path = path
        self.index = load_index(os.path.join(path, "index.ndjson"))
        self.origin = origin_from_video(os.path.basename(self.video_path()))

    def video_path(self):
        """The mp4 to replay (the clock's slave). The filename stamp anchors t=0."""
        vids = glob.glob(os.path.join(self.path, "video", "*.mp4"))
        if not vids:
            raise FileNotFoundError(f"no mp4 under {self.path}/video/")
        return vids[0]

    def sitting_start_ms(self):
        """Where the sitting's speech starts (ms), read from sitting_start.json —
        computed ONCE by detect_start.py (VAD), never here. 0 if not computed."""
        p = os.path.join(self.path, "sitting_start.json")
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as f:
            return int(json.load(f).get("sitting_start_ms", 0))

    def raw_bytes(self, source, t_ms):
        """The raw bytes of `source` current at demo time `t_ms`, or None if the
        source has not appeared yet (causal). Bytes are returned verbatim."""
        ref = current_raw_ref(self.index, self.origin, t_ms, source)
        if ref is None:
            return None
        with open(os.path.join(self.path, "raw", source, ref), "rb") as f:
            return f.read()

    def eliasse_summary(self, t_ms):
        """The captured Eliasse summary current at `t_ms` (a dict), or None. The raw
        eliasse file IS the summary JSON B2 reconstructs the .do responses from."""
        raw = self.raw_bytes("eliasse", t_ms)
        return json.loads(raw) if raw is not None else None

    def referential_bytes(self, name):
        """The frozen referential slice `name` (e.g. 'acteurs'), verbatim, out of the
        clock. None if absent."""
        p = os.path.join(self.path, "referential", f"{name}.json")
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def ground_truth_bytes(self, name):
        """The post-production ground-truth NVS `name` (e.g. 'data.nvs'), verbatim,
        out of the clock — B4's comparison pane, never a B1 input. None if absent."""
        p = os.path.join(self.path, "ground-truth-vod", name)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def _last_raw(self, source):
        """The bytes of the most recent raw snapshot of `source`, or None. Used as
        the NVS fallback when the record has no ground-truth-vod/ pull — the last
        live snapshot is the most complete (the post-prod NVS keeps filling in)."""
        files = sorted(glob.glob(os.path.join(self.path, "raw", source, "*")))
        if not files:
            return None
        with open(files[-1], "rb") as f:
            return f.read()

    def _nvs_sources(self):
        """The (data.nvs, liveplayer.nvs) bytes to build the NVS view from: the
        frozen ground-truth-vod/ pull if present, else the last live raw snapshot
        (richer for records captured without a VOD pull). (None, None) if absent."""
        data = self.ground_truth_bytes("data.nvs") or self._last_raw("data_nvs")
        lp = self.ground_truth_bytes("liveplayer.nvs") or self._last_raw("liveplayer")
        return data, lp

    def nvs_timeline(self):
        """The NVS chapters placed on the video timeline (see nvs_timeline). None if
        no NVS is available anywhere."""
        data, lp = self._nvs_sources()
        return nvs_timeline(data, lp) if data and lp else None

    def nvs_tree(self):
        """The NVS chapters as a nested tree (see nvs_tree), for B4's ancestor-chain
        highlight. None if no NVS is available anywhere."""
        data, lp = self._nvs_sources()
        return nvs_tree(data, lp) if data and lp else None


def current_raw_ref(index, origin, t_ms, source):
    """The raw_ref of `source` current at demo time `t_ms`, or None if none yet.

    Walks the causal snapshot backwards for the most recent tick that carries a
    raw_ref for `source` (unchanged ticks repeat it; a tick may omit it entirely).
    The ref names a file under raw/<source>/ whose bytes are served verbatim.
    """
    for rec in reversed(causal_snapshot(index, origin, t_ms)):
        ref = rec.get("raw_ref", {}).get(source)
        if ref:
            return ref
    return None
