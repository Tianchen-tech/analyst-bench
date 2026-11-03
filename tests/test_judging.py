"""Judgment validation and panel combination (judge/judge.py, scripts/panel_combine.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import panel_combine as pc
from judge import judge as J

HARNESS = Path(__file__).resolve().parents[1] / "harness"

PACKET = {"task_id": "Q12",
          "atoms": [{"atom": "a", "max": 10, "state": "pending"}, {"atom": "done", "max": 5, "state": "auto"}],
          "claims": [{"ref": "/claims/0", "auto_verdict": None}, {"ref": "/result/metrics/0", "auto_verdict": "correct"}],
          "flags": {"critical_review": ["crit"], "caps_review": {"cap": 50}}, "trap_opportunities": ["trap"]}


def judgment(verdict="correct", warned=False, awarded=10, crit=False, trap=True, **extra) -> dict:
    claim = {"verdict": verdict, "warned": warned}
    if verdict == "wrong":
        claim.update(codes=["E14"], severity=2)
    if warned:
        claim["qualification_ref"] = "warnings[0]"
    log = {"atoms": {"a": {"awarded": awarded, "reason": "r"}},
           "claims": {"/claims/0": claim, "/result/metrics/0": {"verdict": "correct", "warned": False}},
           "memo_claims": [], "memo_reviewed": True, "critical": {"crit": crit}, "caps": {"cap": False},
           "substantive": True, "traps": {"trap": trap}, "disputes": []}
    log.update(extra)
    return log


# ------------------------------------------------------------------------------------------------- majority --

def test_majority_with_a_clear_winner():
    assert J._majority(["wrong", "correct", "wrong"]) == ("wrong", True)
    assert J._majority([True, False]) == (True, False)


def test_a_tie_goes_to_the_first_value_in_order():
    assert J._majority(["unverifiable", "wrong", "correct"]) == ("unverifiable", False)
    assert J._majority([{"x": 1}, {"x": 2}]) == ({"x": 1}, False)


def test_ties_do_not_depend_on_hash_randomization():
    code = "from judge.judge import _majority; print(_majority(['correct', 'wrong', 'unverifiable'])[0])"
    seen = set()
    for seed in range(6):
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=str(HARNESS))
        seen.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.strip())
    assert seen == {"correct"}


# ----------------------------------------------------------------------------------------------- validation --

def test_a_complete_judgment_has_no_problems():
    assert J.problems(judgment(), PACKET) == []


def test_problems_lists_what_a_judgment_lacks():
    log = judgment(verdict="wrong")
    del log["claims"]["/claims/0"]["codes"]
    del log["traps"]["trap"]
    log["atoms"]["a"]["awarded"] = 11                                     # above the atom's maximum
    out = J.problems(log, PACKET)
    assert "atom a (0..10)" in out
    assert "claim /claims/0: codes for a wrong claim" in out
    assert "traps: trap" in out
    assert J.problems("not a dict", PACKET) == ["no JSON object"]


def test_keep_automatic_restores_the_arithmetic_verdict_and_records_the_objection():
    log = judgment()
    log["claims"]["/result/metrics/0"] = {"verdict": "wrong", "warned": False, "codes": ["E03"], "severity": 2}
    kept = J.keep_automatic(log, PACKET)
    claim = kept["claims"]["/result/metrics/0"]
    assert claim["verdict"] == "correct" and claim["semantic_verdict"] == "wrong" and "codes" not in claim
    assert any("automatic kept" in d for d in kept["disputes"])
    assert log["claims"]["/result/metrics/0"]["verdict"] == "wrong"         # the input is not modified


@pytest.mark.parametrize("text", [
    '{"atoms": {}, "claims": {}}',
    'Here is my review:\n```json\n{"atoms": {}, "claims": {}}\n```',
    '{"type": "result", "result": "{\\"atoms\\": {}, \\"claims\\": {}}"}',
])
def test_extract_json_finds_the_judgment(text: str):
    assert J.extract_json(text) == {"atoms": {}, "claims": {}}


# ---------------------------------------------------------------------------------------------- combination --

def test_consensus_of_three_uses_majority_and_median():
    logs = [judgment(verdict="wrong", awarded=0), judgment(verdict="wrong", awarded=5), judgment(verdict="correct", awarded=10)]
    out, unresolved = J.consensus(logs, PACKET)
    assert unresolved == []
    assert out["claims"]["/claims/0"]["verdict"] == "wrong"
    assert out["atoms"]["a"]["awarded"] == 5


def test_consensus_reports_a_three_way_split():
    logs = [judgment(verdict="wrong"), judgment(verdict="correct"), judgment(verdict="unverifiable")]
    _, unresolved = J.consensus(logs, PACKET)
    assert any(u.startswith("claim /claims/0") for u in unresolved)


def test_two_judges_lenient_and_strict():
    objecting = dict(judgment(verdict="wrong", awarded=0, crit=True, trap=False), judge={"judge": "gpt"})
    accepting = dict(judgment(verdict="correct", awarded=10, crit=False, trap=True), judge={"judge": "claude"})
    lenient = pc.combine_two([objecting, accepting], PACKET, strict=False)
    strict = pc.combine_two([objecting, accepting], PACKET, strict=True)
    assert lenient["claims"]["/claims/0"]["verdict"] == "correct"
    assert strict["claims"]["/claims/0"] == {"verdict": "wrong", "warned": False, "codes": ["E14"], "severity": 2}
    assert (lenient["atoms"]["a"]["awarded"], strict["atoms"]["a"]["awarded"]) == (10.0, 0.0)
    assert (lenient["critical"]["crit"], strict["critical"]["crit"]) == (False, True)
    assert (lenient["traps"]["trap"], strict["traps"]["trap"]) == (True, False)


def test_three_judges_resolve_a_split_claim_by_the_declared_variant():
    logs = {"grok": judgment(verdict="correct"), "gpt": judgment(verdict="wrong"), "claude": judgment(verdict="unverifiable")}
    lenient = pc.combine_logs(logs, PACKET, "lenient")
    strict = pc.combine_logs(logs, PACKET, "strict")
    assert lenient["claims"]["/claims/0"]["verdict"] == "unverifiable"    # first non-wrong reading in provider order
    assert strict["claims"]["/claims/0"]["verdict"] == "wrong"
    assert lenient["panel_notes"] == ["/claims/0: three-way split resolved by the lenient rule"]


def test_three_judges_stop_on_a_split_that_is_not_a_claim():
    weights = [{"A": {"US": w}, "B": {"US": w}, "reported": {"A": 1, "B": 1}} for w in (0.1, 0.2, 0.3)]
    logs = {name: judgment(q16_weights=w) for name, w in zip(("gpt", "claude", "grok"), weights)}
    with pytest.raises(ValueError, match="no majority on q16_weights"):
        pc.combine_logs(logs, PACKET, "lenient")


def test_the_combined_result_does_not_depend_on_the_order_logs_are_given():
    a = {"gpt": judgment(verdict="wrong"), "claude": judgment(verdict="correct")}
    b = dict(reversed(list(a.items())))
    assert pc.combine_logs(a, PACKET, "strict") == pc.combine_logs(b, PACKET, "strict")
