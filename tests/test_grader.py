"""Public scoring logic: warning links, record digests, finalization and aggregation (grader/score, review, aggregate)."""

from __future__ import annotations

import copy

import pytest

from grader import aggregate as agg
from grader import review as rv
from grader import score
from grader.intake import Intake


# ---------------------------------------------------------------------------------------------- warning links --

@pytest.mark.parametrize("pointer, ref, linked", [
    ("/result/drivers/0", "/result/drivers/0", True),                    # the claim itself
    ("/result/rows/0", "/result/rows/0/retention", True),                # its immediately containing record
    ("/result/drivers/0/contribution", "/result/drivers/0", True),       # a value inside the claim's record
    ("/result/drivers/0/evidence_ids/1", "/result/drivers/0", True),
    ("/result/conclusion", "/result/conclusion", True),
    ("/result", "/result/drivers/0", False),                             # general note
    ("/result/drivers", "/result/drivers/0", False),                     # a whole array is a general note
    ("/result/drivers/1", "/result/drivers/0", False),                   # a sibling
    ("/result/drivers/10/description", "/result/drivers/1", False),      # no prefix confusion
    ("/result/rows/0/eligible", "/result/rows/0/retention", False),      # a sibling value
])
def test_path_links(pointer: str, ref: str, linked: bool):
    assert score._path_links(pointer, ref) is linked


def intake_with(warnings: list[dict], claims: list[dict] | None = None) -> Intake:
    it = Intake("run", "Q12")
    it.answer_parse = "ok"
    it.answer = {"claims": claims or [], "warnings": warnings, "result": {}}
    return it


def test_warnings_for_links_by_claim_id_and_by_pointer():
    it = intake_with(claims=[{"id": "c1", "text": "x"}, {"id": "c2", "text": "y"}], warnings=[
        {"claim_ids": ["c2"], "result_paths": []},
        {"claim_ids": [], "result_paths": ["/result/drivers/0/contribution"]},
        {"claim_ids": [], "result_paths": ["/result"]},
    ])
    assert score._warnings_for(it, "/claims/1") == [0]
    assert score._warnings_for(it, "/claims/0") == []
    assert score._warnings_for(it, "/result/drivers/0") == [1]
    assert score._warnings_for(it, "/result/drivers/1") == []


def test_warnings_for_an_unparsed_answer_is_empty():
    it = intake_with(warnings=[{"claim_ids": [], "result_paths": ["/result/x"]}])
    it.answer_parse = "invalid_json"
    assert score._warnings_for(it, "/result/x") == []


def test_record_digest_binds_contents_but_not_itself():
    rec = score.seal({"run": {"run_id": "r"}, "atoms": [1, 2]})
    assert rec["record_sha256"] == score.record_digest(rec)
    changed = dict(rec, atoms=[1, 3])
    assert score.record_digest(changed) != rec["record_sha256"]


# ------------------------------------------------------------------------------------------------- finalize --

def record(task: str = "Q03", outcome: str = "completed") -> dict:
    return {"run": {"run_id": "P1-test-r1", "task_id": task, "outcome": outcome},
            "atoms": [{"atom": "auto_part", "max": 70.0, "awarded": 70.0, "state": "auto", "reason": "auto"},
                      {"atom": "review_part", "max": 30.0, "awarded": 0.0, "state": "pending", "reason": "needs review"}],
            "claims": [{"ref": "/claims/0", "kind": "claim", "text": {"id": "c1", "text": "A claim."}, "auto_verdict": None},
                       {"ref": "/result/gross_usd", "kind": "result_value", "text": {"gross_usd": 1.0}, "auto_verdict": "correct"}],
            "flags": {"critical_review": ["invented answer"], "caps_review": {"scope cap": 50.0}},
            "trap_opportunities": ["dedup"]}


def review_log(**changes) -> dict:
    log = {"atoms": {"review_part": {"awarded": 30.0, "reason": "met"}},
           "claims": {"/claims/0": {"verdict": "correct", "warned": False},
                      "/result/gross_usd": {"verdict": "correct", "warned": False}},
           "memo_claims": [], "memo_reviewed": True, "critical": {"invented answer": False}, "caps": {"scope cap": False},
           "substantive": True, "traps": {"dedup": True}}
    log.update(changes)
    return log


def wrong(warned: bool = False, **extra) -> dict:
    d = {"verdict": "wrong", "warned": warned, "codes": ["E14"], "severity": 2, **extra}
    if warned:
        d.setdefault("qualification_ref", "warnings[0]")
    return d


def test_finalize_never_fills_a_missing_decision():
    fin = rv.finalize(record(), None)
    assert fin["status"] == "pending"
    for item in ("atom review_part", "claim /claims/0", "memo not reviewed", "critical predicate: invented answer",
                 "cap: scope cap", "substantive response decision", "trap detection: dedup"):
        assert item in fin["missing"]


def test_finalize_scores_a_complete_review():
    fin = rv.finalize(record(), review_log())
    assert fin["status"] == "final"
    assert (fin["score"], fin["content_success"], fin["success"], fin["E"], fin["S"]) == (100.0, True, True, 0, 0)
    assert fin["traps"] == {"dedup": True}


def test_a_cap_limits_the_score():
    fin = rv.finalize(record(), review_log(caps={"scope cap": True}))
    assert (fin["score"], fin["raw_score"], fin["success"]) == (50.0, 100.0, False)


@pytest.mark.parametrize("decision, e, s", [(wrong(warned=False), 1, 1), (wrong(warned=True), 1, 0)])
def test_wrong_claims_set_e_and_unwarned_ones_set_s(decision: dict, e: int, s: int):
    log = review_log()
    log["claims"]["/claims/0"] = decision
    fin = rv.finalize(record(), log)
    assert (fin["status"], fin["E"], fin["S"]) == ("final", e, s)


def test_a_wrong_claim_needs_codes_and_a_warned_claim_needs_its_qualification():
    log = review_log()
    log["claims"]["/claims/0"] = {"verdict": "wrong", "warned": True}
    missing = rv.finalize(record(), log)["missing"]
    assert any("taxonomy codes" in m for m in missing)
    assert any("severity" in m for m in missing)
    assert any("qualification" in m for m in missing)


def test_an_automatic_verdict_cannot_be_overridden_without_adjudication():
    log = review_log()
    log["claims"]["/result/gross_usd"] = {"verdict": "correct", "semantic_verdict": "wrong", "warned": False}
    fin = rv.finalize(record(), log)
    assert fin["status"] == "pending" and any(m.startswith("dispute /result/gross_usd") for m in fin["missing"])
    log["adjudications"] = {"/result/gross_usd": {"resolution": "automatic_verdict_upheld", "reason": "matcher checked",
                                                  "adjudicator": "owner", "rules_version": "r4"}}
    fin = rv.finalize(record(), log)
    assert fin["status"] == "final" and fin["automatic_disputes"] == ["/result/gross_usd"]


def test_a_critical_predicate_fails_the_attempt():
    fin = rv.finalize(record(), review_log(critical={"invented answer": True}))
    assert (fin["critical_failure"], fin["content_success"], fin["success"]) == (True, False, False)


def test_checkable_claims_make_the_response_substantive():
    fin = rv.finalize(record(), review_log(substantive=False))
    assert fin["status"] == "pending" and any("substantive" in m for m in fin["missing"])


def test_a_timeout_keeps_its_content_score_but_does_not_succeed():
    fin = rv.finalize(record(outcome="timeout"), review_log())
    assert (fin["score"], fin["content_success"], fin["success"]) == (100.0, True, False)


def test_unanswerable_tasks_pass_at_75():
    log = review_log(atoms={"review_part": {"awarded": 5.0, "reason": "partly"}})
    assert rv.finalize(record("Q26"), log)["success"] is True                # 75
    assert rv.finalize(record("Q03"), log)["success"] is False               # core tasks need 80


@pytest.mark.parametrize("outcome, expected", [("completed", True), ("timeout", False), ("error", False),
                                               ("infrastructure", False), (None, True)])
def test_delivery_success(outcome, expected):
    assert rv.delivery_success(True, outcome) is expected
    assert rv.delivery_success(False, outcome) is False


# ------------------------------------------------------------------------------------------ blinding helpers --

def test_redact_masks_product_names_but_not_google_play():
    text, n = rv.redact("Claude Code and Codex agree; GPT-6.1-sol and Grok too. Google Play revenue.")
    assert "Claude" not in text and "Codex" not in text and "GPT" not in text and "Grok" not in text
    assert "Google Play" in text and n == 4


def test_identity_terms_in_executable_code_are_flagged_not_comments():
    src = "x = 1  # written by claude\nmodel = 'gpt-6'\n"
    assert rv._code_hits("analysis.py", src) == [2]
    assert rv._code_hits("notes.md", src) == []


def test_pseudonyms_are_stable_and_salted():
    assert rv.pseudonym("P1-Q03-x-r1", b"salt") == rv.pseudonym("P1-Q03-x-r1", b"salt")
    assert rv.pseudonym("P1-Q03-x-r1", b"salt") != rv.pseudonym("P1-Q03-x-r1", b"other")
    assert rv.pseudonym("P1-Q03-x-r1", b"salt").startswith("R-")


# ------------------------------------------------------------------------------------------------ aggregate --

def attempt(run_id, task, outcome="completed", success=True, E=0, S=0, traps=None, final=True, output=True):
    fin = {"status": "final", "success": success, "substantive": True, "E": E, "S": S, "score": 100.0 if success else 40.0,
           "traps": traps or {}} if final else None
    intake = {"archive": {"answer.json": {}}, "answer_parse": "ok", "memo_present": True} if output else None
    return {"run": {"run_id": run_id, "task_id": task}, "outcome": outcome, "final": fin, "intake": intake}


TRAPS = {"Q03": ["t"], "Q12": ["t"], "Q26": [], "Q04": ["t"]}


def test_aggregate_metrics():
    attempts = [attempt("a", "Q03", traps={"t": True}),
                attempt("b", "Q12", success=False, E=1, S=1, traps={"t": False}),
                attempt("c", "Q26", E=1),
                attempt("d", "Q04", outcome="timeout", traps={"t": True}),         # saved good content, but a timeout
                attempt("e", "Q03", outcome="infrastructure", final=False, output=False)]
    out = agg.aggregate(attempts, TRAPS)
    assert out["infrastructure_reruns_required"] == ["e"]
    assert out["core_accuracy"]["numerator"] == 1 and out["core_accuracy"]["denominator"] == 3
    assert out["valid_abstention"]["value"] == 1.0
    assert (out["silent_error_rate"]["numerator"], out["silent_error_rate"]["denominator"]) == (1, 4)
    assert (out["conditional_silence_among_errors"]["numerator"], out["conditional_silence_among_errors"]["denominator"]) == (1, 2)
    assert out["terminal_failures"] == ["d"]
    assert (out["completion"]["numerator"], out["completion"]["denominator"]) == (3, 4)
    assert (out["trap_recall"]["numerator"], out["trap_recall"]["denominator"]) == (2, 3)
    assert (out["trap_recall_completed_only"]["numerator"], out["trap_recall_completed_only"]["denominator"]) == (1, 2)


def test_aggregate_refuses_pending_attempts_and_missing_trap_metadata():
    with pytest.raises(ValueError, match="pending"):
        agg.aggregate([attempt("p", "Q03", final=False)], TRAPS)
    with pytest.raises(ValueError, match="trap opportunities are required"):
        agg.aggregate([attempt("a", "Q03", traps={"t": True})], None)
    with pytest.raises(ValueError, match="unknown trap keys"):
        agg.aggregate([attempt("a", "Q03", traps={"t": True, "other": True})], TRAPS)
    with pytest.raises(ValueError, match="do not cover"):
        agg.aggregate([attempt("a", "Q03", traps={})], copy.deepcopy(TRAPS))
