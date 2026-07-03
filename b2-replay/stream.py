"""B2 live streamer — re-broadcast the record's mp4 as a LIVE sliding-window HLS.

The point (decided 2026-07-03): consumers must see the replay in the exact shape
of the real live — a .m3u8 whose edge advances at real-time rate — so B1 and B4
read it precisely like the Vodalys direct. The streamer is a slave of the master
clock: play → ffmpeg -re from the clock's t; pause → stop; seek → restart at the
new t. Both advance at real-time rate, so edge ≈ clock for the whole run.

ffmpeg writes into a private temp dir; `file()` is the only read path and
whitelists names, so the HTTP layer cannot be walked out of the dir.
"""
import os
import re
import subprocess
import tempfile
import threading

_SERVABLE = re.compile(r"stream\.m3u8|seg_\d+\.ts")

CONTENT_TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t"}


class LiveStreamer:
    def __init__(self, video_path):
        self._video = video_path
        self._dir = tempfile.mkdtemp(prefix="ariane-live-")
        self._proc = None
        self._lock = threading.Lock()

    def set_video(self, video_path):
        """Point at another sitting's mp4 (record switch); stops the stream."""
        with self._lock:
            self._stop_locked()
            self._video = video_path

    def start(self, t_ms):
        """(Re)start the live edge at `t_ms` into the video."""
        with self._lock:
            self._stop_locked()
            self._clean_locked()
            self._proc = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-re", "-ss", f"{t_ms / 1000:.3f}", "-i", self._video,
                 "-c", "copy", "-f", "hls", "-hls_time", "4",
                 "-hls_list_size", "6", "-hls_flags", "delete_segments",
                 "-hls_segment_filename", os.path.join(self._dir, "seg_%05d.ts"),
                 os.path.join(self._dir, "stream.m3u8")])

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def _clean_locked(self):
        for f in os.listdir(self._dir):
            try:
                os.unlink(os.path.join(self._dir, f))
            except OSError:
                pass

    def file(self, name):
        """Bytes of a servable stream file (whitelisted), or None."""
        if not _SERVABLE.fullmatch(name):
            return None
        try:
            with open(os.path.join(self._dir, name), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None


def list_records(records_dir, current=None):
    """The replayable capture bundles under `records_dir`, for B4's picker.

    Replayable = has an index.ndjson and at least one video/*.mp4. Each entry:
    {name, current}. Sorted by name (dates sort chronologically)."""
    out = []
    for name in sorted(os.listdir(records_dir)):
        path = os.path.join(records_dir, name)
        if not os.path.isdir(path):
            continue
        if not os.path.exists(os.path.join(path, "index.ndjson")):
            continue
        import glob as _glob
        if not _glob.glob(os.path.join(path, "video", "*.mp4")):
            continue
        out.append({"name": name, "current": name == current})
    return out


def safe_record_name(name):
    """A record name usable as a path component (no traversal), else None."""
    if name and re.fullmatch(r"[\w.-]+", name) and ".." not in name:
        return name
    return None
