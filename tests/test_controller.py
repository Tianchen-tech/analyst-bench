"""Process tracking and the kill routine (runners/controller.py), plus availability signals."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from types import SimpleNamespace

import pytest

from runners import controller as ctl

START_A, START_B = "Mon Nov 3 10:00:00 2026", "Mon Nov 3 10:05:00 2026"


def test_parse_process_table_reads_pid_ppid_pgid_and_start_and_skips_zombies():
    out = ("  100     1   100 Ss   Mon Nov  3 10:00:00 2026\n"
           "  101   100   100 S+   Mon Nov  3 10:00:01 2026\n"
           "  102   101   100 Z    Mon Nov  3 10:00:02 2026\n"
           "garbage line\n")
    assert ctl._parse_process_table(out) == {100: (1, 100, "Mon Nov 3 10:00:00 2026"), 101: (100, 100, "Mon Nov 3 10:00:01 2026")}


def test_descendants_walks_the_whole_tree():
    table = {10: (1, 10, "s10"), 11: (10, 10, "s11"), 12: (11, 10, "s12"), 13: (1, 13, "s13")}
    assert ctl._descendants(10, table) == {11: "s11", 12: "s12"}
    assert ctl._descendants(13, table) == {}


def proc(pid: int = 100, returncode=None) -> SimpleNamespace:
    return SimpleNamespace(pid=pid, returncode=returncode, wait=lambda timeout=None: 0)


def test_kill_targets_skip_a_reused_pid():
    known = {200: START_A, 201: START_A, 202: START_A}
    table = {200: (1, 999, START_A),      # same process, reparented and in its own group: still ours
             201: (1, 999, START_B),      # pid reused by a later, unrelated process
             300: (200, 999, START_B)}    # a child of a verified process
    assert ctl._kill_targets(proc(returncode=0), known, table) == {200: START_A, 300: START_B}


def test_group_members_count_while_the_leader_is_unreaped_or_its_pid_is_free():
    table = {150: (1, 100, START_A)}      # an orphan still in the run's process group (pgid = leader pid 100)
    assert ctl._kill_targets(proc(returncode=None), {}, table) == {150: START_A}
    assert ctl._kill_targets(proc(returncode=0), {}, table) == {150: START_A}
    reused = {**table, 100: (1, 100, START_B)}              # leader reaped and pid 100 now belongs to someone else
    assert ctl._kill_targets(proc(returncode=0), {}, reused) == {}


def test_kill_tree_never_signals_a_reused_pid(monkeypatch):
    tables = iter([{201: (1, 999, START_B), 300: (100, 100, START_A)},     # TERM round
                   {201: (1, 999, START_B), 300: (100, 100, START_A)},     # KILL round
                   {201: (1, 999, START_B)}])                              # afterwards
    sent: list[tuple[str, int, int]] = []
    monkeypatch.setattr(ctl, "_process_table", lambda: next(tables))
    monkeypatch.setattr(ctl.os, "kill", lambda pid, sig: sent.append(("kill", pid, sig)))
    monkeypatch.setattr(ctl.os, "killpg", lambda pid, sig: sent.append(("killpg", pid, sig)))
    monkeypatch.setattr(ctl.time, "sleep", lambda s: None)
    known = {201: START_A}
    left = ctl._kill_tree(proc(returncode=None), known)
    assert left == 0
    assert all(pid != 201 for _, pid, _ in sent)
    assert ("killpg", 100, signal.SIGTERM) in sent and ("kill", 300, signal.SIGKILL) in sent
    assert known == {201: START_A, 300: START_A}                            # descendants found while killing are recorded


@pytest.mark.skipif(os.name != "posix", reason="needs ps and POSIX process groups")
def test_kill_tree_stops_a_real_process_tree_including_an_orphan():
    # a background sleep, and an orphan: a subshell starts a sleep and exits, so the sleep is reparented but stays in
    # the run's process group
    p = subprocess.Popen(["/bin/sh", "-c", "sleep 60 & (sleep 60 &) ; sleep 60"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        known: dict[int, str] = {}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            known.update(ctl._descendants(p.pid))
            group = [pid for pid, info in ctl._process_table().items() if info[1] == p.pid and pid != p.pid]
            if len(group) >= 3:
                break
            time.sleep(0.1)
        assert len(group) >= 3, "the test processes did not start"
        assert ctl._kill_tree(p, known) == 0
        assert p.returncode is not None
        assert not [pid for pid, info in ctl._process_table().items() if info[1] == p.pid]
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def test_quota_telemetry_is_not_an_availability_signal(tmp_path):
    log = tmp_path / "transcript.jsonl"
    log.write_text('{"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning"}}\n'
                   '{"type": "assistant", "text": "counted 1429 rows"}\n', encoding="utf-8")
    assert ctl.availability_signals(log) == []
    log.write_text('{"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}\n'
                   "Error: 429 Too Many Requests\n", encoding="utf-8")
    assert len(ctl.availability_signals(log)) == 2
