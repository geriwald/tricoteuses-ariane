"""Tests for B2's transport dispatch — the UI drives the clock by commands only,
never by pushing `t` (spec §B2). apply_transport(clock, command, params) mutates the
MasterClock and returns its state dict {t_ms, playing}. Tested without a socket.
"""
from replay import MasterClock
import server


class FakeTime:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    def tick(self, s): self.now += s


def test_play_then_state_reports_playing():
    clk = MasterClock(now=FakeTime())
    state = server.apply_transport(clk, "play", {})
    assert state == {"t_ms": 0, "playing": True}


def test_pause_freezes_and_reports():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    server.apply_transport(clk, "play", {})
    ft.tick(2.0)
    state = server.apply_transport(clk, "pause", {})
    assert state == {"t_ms": 2000, "playing": False}


def test_seek_absolute_takes_t_param():
    clk = MasterClock(now=FakeTime())
    state = server.apply_transport(clk, "seek", {"t": "120000"})
    assert state == {"t_ms": 120000, "playing": False}


def test_seek_by_takes_delta_param_and_can_go_back():
    clk = MasterClock(now=FakeTime())
    server.apply_transport(clk, "seek", {"t": "60000"})
    server.apply_transport(clk, "seek_by", {"delta": "30000"})
    state = server.apply_transport(clk, "seek_by", {"delta": "-80000"})
    assert state["t_ms"] == 10000


def test_seek_zero_via_seek_with_t_zero():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    server.apply_transport(clk, "play", {}); ft.tick(50)
    state = server.apply_transport(clk, "seek", {"t": "0"})
    assert state["t_ms"] == 0


def test_unknown_command_raises():
    clk = MasterClock(now=FakeTime())
    try:
        server.apply_transport(clk, "warp", {})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_clock_payload_carries_origin_and_broadcast_wall():
    # B4 needs the broadcast date/time = origin + t, so /clock exposes the origin.
    from datetime import datetime, timezone, timedelta
    origin = datetime(2026, 6, 26, 21, 31, 9, tzinfo=timezone(timedelta(hours=2)))
    ft = FakeTime()
    clk = MasterClock(now=ft)
    server.apply_transport(clk, "seek", {"t": "120000"})  # +2 min
    payload = server.clock_payload(clk, origin)
    assert payload["t_ms"] == 120000
    assert payload["playing"] is False
    assert payload["origin"] == origin.isoformat()
    # broadcast wall = 21:31:09 + 2min = 21:33:09
    assert payload["wall"] == "2026-06-26T21:33:09+02:00"
