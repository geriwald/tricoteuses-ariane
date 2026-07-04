#!/usr/bin/env python3
"""Run Ariane option 3 against a local replay with CPU faster-whisper.

Starts:
  B2 replay on /live/stream.m3u8
  B1 weaver_live.py with --backend chunked --device cpu
  B4 UI

The script blocks until B1 exits. By default B1 reads 3600 source seconds, then
all child processes are stopped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD = REPO_ROOT / "data" / "2026-06-30-aprem"
DEFAULT_CPU_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


class ManagedProcess:
    def __init__(self, name: str, cmd: list[str], log_path: Path):
        self.name = name
        self.cmd = cmd
        self.log_path = log_path
        self.log_file = log_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )

    def terminate(self, timeout: float = 10.0) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=timeout)
        self.log_file.close()


def tail(path: Path, lines: int = 40) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(data[-lines:])


def request(url: str, *, method: str = "GET", timeout: float = 5.0) -> bytes:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def get_json(url: str, timeout: float = 5.0) -> dict:
    return json.loads(request(url, timeout=timeout).decode("utf-8"))


def wait_http(url: str, timeout_s: float, *, method: str = "GET") -> None:
    deadline = time.time() + timeout_s
    last: Exception | None = None
    while time.time() < deadline:
        try:
            request(url, method=method, timeout=5.0)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced on timeout
            last = exc
            time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last}")


def wait_log_contains(proc: ManagedProcess, needle: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.proc.poll() is not None:
            raise RuntimeError(
                f"{proc.name} exited before {needle!r}. Log tail:\n{tail(proc.log_path)}"
            )
        if needle in proc.log_path.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"timed out waiting for {needle!r} in {proc.name}. Log tail:\n{tail(proc.log_path)}"
    )


def read_sitting_start_ms(record: Path) -> int:
    path = record / "sitting_start.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("sitting_start_ms", 0))


def validate_record(record: Path) -> None:
    if not (record / "index.ndjson").exists():
        raise FileNotFoundError(f"missing index.ndjson in {record}")
    if not list((record / "video").glob("*.mp4")):
        raise FileNotFoundError(f"missing video/*.mp4 in {record}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run option 3 locally on CPU")
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD,
                        help="B3 capture bundle replayed by B2")
    parser.add_argument("--duration-seconds", type=float, default=3600,
                        help="source seconds transcribed by B1")
    parser.add_argument("--start-ms", type=int, default=None,
                        help="B2 clock start; default: record sitting_start_ms")
    parser.add_argument("--time-offset-ms", type=int, default=None,
                        help="B1 timestamp offset; default: --start-ms")
    parser.add_argument("--model", default=DEFAULT_CPU_MODEL,
                        help="faster-whisper model for CPU; use small only after repairing/downloading that cache")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--chunk-seconds", type=float, default=30.0)
    parser.add_argument("--beam", type=int, default=1)
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument("--allow-model-download", action="store_true",
                        help="allow Hugging Face download if the model is not cached")
    parser.add_argument("--b2-port", type=int, default=8000)
    parser.add_argument("--b1-port", type=int, default=8100)
    parser.add_argument("--b4-port", type=int, default=8080)
    parser.add_argument("--no-b4", action="store_true")
    parser.add_argument("--keep-servers", action="store_true",
                        help="leave B2/B4 running after B1 exits")
    args = parser.parse_args()

    record = args.record
    if not record.is_absolute():
        record = (REPO_ROOT / record).resolve()
    validate_record(record)

    start_ms = args.start_ms if args.start_ms is not None else read_sitting_start_ms(record)
    time_offset_ms = args.time_offset_ms if args.time_offset_ms is not None else start_ms
    runs_root = REPO_ROOT / ".runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="option3-cpu-", dir=runs_root))
    thread_out = log_dir / "thread.ndjson"
    print(f"Logs: {log_dir}", flush=True)

    b2 = f"http://127.0.0.1:{args.b2_port}"
    b1 = f"http://127.0.0.1:{args.b1_port}"
    hls = f"{b2}/live/stream.m3u8"

    processes: list[ManagedProcess] = []
    try:
        print("[1/5] Starting B2 replay...", flush=True)
        b2_proc = ManagedProcess(
            "b2",
            [sys.executable, "b2-replay/server.py", "--record", str(record),
             "--records-dir", str(record.parent), "--port", str(args.b2_port)],
            log_dir / "b2.log",
        )
        processes.append(b2_proc)
        wait_http(f"{b2}/clock", 30)
        request(f"{b2}/clock/seek?t={start_ms}", method="POST")

        # B1 reads the VOD file DIRECTLY, not B2's real-time HLS edge: on CPU the
        # chunked STT runs ~0.46x realtime, so against B2's -re sliding window it
        # falls behind, segments get deleted, and B1 reconnects to the live edge —
        # skipping content. flow_s (audio actually read) then decouples from the
        # video's currentTime and the horodatage drifts. Reading the file at B1's
        # own pace (contiguous, seeked to sitting_start) makes flow_s == video
        # position, so t == the UI's seek target to the millisecond. B2 stays up
        # only to serve the referentials (agenda/actors/organes) below.
        video = str(next(iter(sorted((record / "video").glob("*.mp4")))))
        b1_cmd = [
            sys.executable, "b1-weaver/weaver_live.py",
            "--source", video,
            "--start-seconds", f"{start_ms / 1000:.3f}",
            "--agenda", f"{b2}/local/derouleur/derouleur.json",
            "--actors", f"{b2}/referential/acteurs.json",
            "--organes", f"{b2}/referential/organes.json",
            "--port", str(args.b1_port),
            "--out", str(thread_out),
            "--backend", "chunked",
            "--device", "cpu",
            "--model", args.model,
            "--compute-type", args.compute_type,
            "--chunk-seconds", str(args.chunk_seconds),
            "--beam", str(args.beam),
            "--cpu-threads", str(args.cpu_threads),
            "--max-seconds", str(args.duration_seconds),
            "--time-offset-ms", str(time_offset_ms),
        ]
        if not args.allow_model_download:
            b1_cmd.append("--local-files-only")
        print("[2/5] Loading B1 CPU model and waiting for readiness...", flush=True)
        b1_proc = ManagedProcess("b1", b1_cmd, log_dir / "b1.log")
        processes.append(b1_proc)
        wait_log_contains(b1_proc, "[ready]", 120)
        print("[3/5] B1 ready.", flush=True)

        if not args.no_b4:
            print("[4/5] Starting B4 UI...", flush=True)
            b4_proc = ManagedProcess(
                "b4",
                [sys.executable, "b4-ui/serve.py", "--port", str(args.b4_port)],
                log_dir / "b4.log",
            )
            processes.append(b4_proc)
            wait_http(f"http://127.0.0.1:{args.b4_port}", 30)

        print("[5/5] Starting B2 clock and HLS...", flush=True)
        request(f"{b2}/clock/play", method="POST")
        wait_http(hls, 45, method="HEAD")

        print("Option 3 CPU is running.")
        print(f"Record: {record}")
        print(f"B2: {b2}")
        print(f"B1 thread: {b1}/thread")
        if not args.no_b4:
            print(f"B4 UI: http://127.0.0.1:{args.b4_port}")
        print(f"Logs: {log_dir}")
        print(f"Thread output: {thread_out}")
        print(f"Duration: {args.duration_seconds:g}s, start_ms={start_ms}, offset_ms={time_offset_ms}")

        return_code = b1_proc.proc.wait()
        if return_code:
            print(f"B1 exited with code {return_code}. Log tail:\n{tail(b1_proc.log_path)}", file=sys.stderr)
        else:
            print("B1 completed normally; requested duration was fully processed.")
            print(f"Thread output: {thread_out}")
        return return_code
    except KeyboardInterrupt:
        print("Interrupted; stopping child processes.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - command-line diagnostic
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            request(f"{b2}/clock/pause", method="POST", timeout=2.0)
        except Exception:
            pass
        if not args.keep_servers:
            for proc in reversed(processes):
                proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())







