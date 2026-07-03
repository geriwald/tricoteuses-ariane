"""Tests for the capture→resolution auto-chaining in record_sitting.py.

Focus: when the sitting ends (auto-stop), the recorder schedules the referential
resolution ~30 min later via a systemd --user one-shot timer, and writes the exact
command to the log (Telegram carries only the event, not the command — Géraud reads
it on his phone). The command-building is pure and unit-tested; the actual spawn is
a thin wrapper.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_sitting as rs


def test_resolution_command_targets_the_record_with_python():
    cmd = rs.resolution_command("/mnt/data/ariane-capture/2026-06-30-evening")
    # the resolver is invoked on this record, with the running interpreter
    assert rs.RESOLVER in cmd
    assert "--record" in cmd
    assert cmd[cmd.index("--record") + 1] == "/mnt/data/ariane-capture/2026-06-30-evening"
    assert cmd[0] == sys.executable


def test_schedule_command_is_a_user_oneshot_timer_with_the_delay():
    sched = rs.schedule_resolution_command(
        "/mnt/data/ariane-capture/2026-06-30-evening", delay_min=30)
    # a non-recurring systemd --user timer, surviving logout, 30 min out
    assert sched[0] == "systemd-run"
    assert "--user" in sched
    assert "--on-active=30min" in sched
    # a stable, collision-free unit name derived from the record basename
    assert any(a.startswith("--unit=ariane-resolve-") for a in sched)
    # the resolver command is appended verbatim
    assert rs.RESOLVER in sched
    assert sched[-1] == "/mnt/data/ariane-capture/2026-06-30-evening"
    assert sched[-2] == "--record"


def test_unit_name_is_filesystem_safe():
    # basenames may carry characters systemd unit names reject; keep [A-Za-z0-9-]
    sched = rs.schedule_resolution_command("/tmp/2026-06-30 evening (live)", delay_min=30)
    unit = next(a for a in sched if a.startswith("--unit="))
    name = unit.split("=", 1)[1]
    assert all(c.isalnum() or c in "-." for c in name), name


def test_systemd_env_provides_runtime_dir_for_cron():
    # under cron XDG_RUNTIME_DIR is unset, which breaks `systemd-run --user`; the
    # recorder must inject it so the auto-chaining works from an unattended cron run
    env = rs.systemd_user_env({"HOME": "/home/geraud", "PATH": "/usr/bin"})
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{os.getuid()}"
    # an already-set value is preserved
    env2 = rs.systemd_user_env({"XDG_RUNTIME_DIR": "/run/user/42"})
    assert env2["XDG_RUNTIME_DIR"] == "/run/user/42"
