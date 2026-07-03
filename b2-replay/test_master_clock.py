"""Tests for B2's master clock — the single authority that owns `t` (spec §B2).

`t` is ms since the sitting's video start. The clock advances at real-time rate
while playing, freezes while paused, and obeys transport commands
(`play/pause/seek(t)/seek(±Δ)/seek(0)`) — never a pushed `t`. The video is its
slave, so the clock must expose `t` at any wall instant without sleeping.

Time is injected (a `now()` callable returning epoch seconds) so the clock is
tested deterministically, no real sleep.
"""
from replay import MasterClock


class FakeTime:
    """A controllable wall clock: starts at 1000.0 s, advances on demand."""
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def test_starts_paused_at_zero():
    clk = MasterClock(now=FakeTime())
    assert clk.t_ms() == 0
    assert not clk.playing


def test_advances_at_real_time_while_playing():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.play()
    ft.tick(2.5)          # 2.5 s of wall time
    assert clk.t_ms() == 2500


def test_frozen_while_paused():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.play()
    ft.tick(1.0)
    clk.pause()
    ft.tick(10.0)         # wall moves, but paused → t frozen
    assert clk.t_ms() == 1000
    assert not clk.playing


def test_resume_continues_from_where_it_paused():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.play(); ft.tick(3.0); clk.pause(); ft.tick(5.0)
    clk.play(); ft.tick(2.0)
    assert clk.t_ms() == 5000   # 3 s + 2 s, the 5 s pause not counted


def test_seek_absolute_sets_t():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.seek(120_000)
    assert clk.t_ms() == 120_000


def test_seek_absolute_while_playing_advances_from_target():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.play()
    clk.seek(120_000)
    ft.tick(1.0)
    assert clk.t_ms() == 121_000


def test_seek_relative_forward_and_back():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.seek(60_000)
    clk.seek_by(30_000)
    assert clk.t_ms() == 90_000
    clk.seek_by(-80_000)
    assert clk.t_ms() == 10_000


def test_seek_never_goes_negative():
    clk = MasterClock(now=FakeTime())
    clk.seek(5_000)
    clk.seek_by(-999_000)
    assert clk.t_ms() == 0


def test_seek_zero_restarts():
    ft = FakeTime()
    clk = MasterClock(now=ft)
    clk.play(); ft.tick(50.0)
    clk.seek(0)
    assert clk.t_ms() == 0
