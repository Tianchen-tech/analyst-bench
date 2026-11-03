"""The wave driver's ledger logic (runners/wave.py): resolution, replacement timing, stops and quota waits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runners import wave as W

SLOTS = [{"order": 0, "product": "Codex", "task": "Q03", "repetition": 1, "block": "r1-Q03"},
         {"order": 1, "product": "Codex", "task": "Q04", "repetition": 1, "block": "r1-Q04"}]


@pytest.fixture
def wave(tmp_path: Path) -> W.Wave:
    return W.Wave(tmp_path, wave_dir=tmp_path, bundle_path=tmp_path / "bundle.json", root=tmp_path,
                  run_slot=lambda *a, **k: {}, check_bundle=lambda: (True, None), executable_sha=lambda product: "x",
                  sleep=lambda s: None, say=lambda m: None)


def bundle() -> W.Bundle:
    return W.Bundle("sha", {"slots": SLOTS, "products": [{"name": "Codex"}]}, {"Codex": {"name": "Codex"}})


def end(slot: str, outcome: str, t: float = 1000.0, **extra) -> dict:
    return {"event": "slot_end", "slot": slot, "product": "Codex", "grader_outcome": outcome, "t": t, **extra}


def test_a_slot_is_resolved_by_a_result_or_by_a_second_infrastructure_outcome():
    st = W.state([end("00", "infrastructure"), end("01", "timeout")])
    assert not st["00"].resolved and st["01"].resolved
    assert W.state([end("00", "infrastructure"), end("00", "infrastructure")])["00"].resolved
    started = W.state([{"event": "slot_start", "slot": "00"}])
    assert started["00"].open_start == {"event": "slot_start", "slot": "00"} and not started["00"].resolved


def test_next_action_runs_slots_in_order_and_delays_a_replacement(wave: W.Wave):
    b = bundle()
    assert wave.next_action(b, []) == (SLOTS[0], 0, 0.0)
    assert wave.next_action(b, [end("00", "completed")]) == (SLOTS[1], 0, 0.0)
    slot, attempt, earliest = wave.next_action(b, [end("00", "infrastructure", failed_at=1000.0)])
    assert (slot, attempt, earliest) == (SLOTS[0], 1, 1000.0 + W.REPLACEMENT_DELAY_S)
    later = wave.next_action(b, [end("00", "infrastructure", failed_at=1000.0, retry_not_before=99999.0)])
    assert later[2] == 99999.0
    assert wave.next_action(b, [end("00", "completed"), end("01", "error")]) is None


def test_consecutive_infrastructure_outcomes_reset_on_an_owner_acknowledgement(wave: W.Wave):
    assert wave.consecutive_infra([end("00", "infrastructure"), end("00", "infrastructure")], "Codex") == 2
    assert wave.consecutive_infra([end("00", "infrastructure"), {"event": "owner_ack"}, end("01", "infrastructure")], "Codex") == 1
    assert wave.consecutive_infra([end("00", "infrastructure"), end("01", "completed")], "Codex") == 0


def test_quota_wait_until(wave: W.Wave, monkeypatch):
    monkeypatch.setattr(W, "now", lambda: 1000.0)
    assert wave.quota_wait_until(None) == (None, "no observation yet")
    assert wave.quota_wait_until({"five_hour": 0.99, "weekly": 0.5}) == (None, "")
    until, why = wave.quota_wait_until({"five_hour": 1.0, "five_hour_resets_at": 1500.0, "weekly": 0.2})
    assert until == 1500.0 and "five-hour 100%" in why
    assert wave.quota_wait_until({"five_hour": 1.0, "five_hour_resets_at": 900.0}) == (None, "reset time passed")


def test_ledger_appends_and_reads_events(tmp_path: Path):
    ledger = W.Ledger(tmp_path / "ledger.jsonl")
    ledger.append("wave_start", bundle_sha256="b")
    ledger.append("slot_start", slot="00")
    assert [e["event"] for e in ledger.events()] == ["wave_start", "slot_start"]
    assert json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])["bundle_sha256"] == "b"


def test_availability_comes_from_product_events_not_from_tool_output(tmp_path: Path):
    (tmp_path / "stderr.log").write_text("", encoding="utf-8")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"type": "user", "content": "rate limit 429 quota in my query output"}) + "\n"
                          + json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning"}}) + "\n",
                          encoding="utf-8")
    assert W.structured_availability("claude_code_print", tmp_path) == []
    with transcript.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}) + "\n")
    assert W.structured_availability("claude_code_print", tmp_path) == ["rate_limit_event status 'rejected'"]
