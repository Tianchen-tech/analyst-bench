"""Stage 5: aggregate finalized attempts (design 5.4). Refuses while any attempt is pending.

Each attempt is {"run": {...}, "outcome": completed|timeout|error|infrastructure, "final": finalize(...) or None,
"intake": intake json or None}. An attempt is a scheduled slot, including failures. Infrastructure outcomes are listed
separately under the failure policy (rerun, never an agent error); they are not silently dropped.
"""

from __future__ import annotations

from typing import Any

from .score import CORE, UNANSWERABLE
from .review import delivery_success


def _ratio(num: int, den: int) -> dict[str, Any]:
    return {"numerator": num, "denominator": den, "value": (num / den) if den else None}


def aggregate(attempts: list[dict[str, Any]], trap_opportunities: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """trap_opportunities: task -> applicable opportunities (from gold); attempts without a final record count as
    undetected for the all-attempts recall and are excluded from the completed-only recall (design 5.4)."""
    has_output = lambda a: bool((a.get("intake") or {}).get("archive"))
    pending = [a["run"]["run_id"] for a in attempts if a.get("outcome") != "infrastructure" and has_output(a)
               and (a.get("final") or {}).get("status") != "final"]
    if pending:
        raise ValueError(f"cannot aggregate: attempts still pending review: {pending}")
    infra = [a["run"]["run_id"] for a in attempts if a.get("outcome") == "infrastructure"]
    scored = [a for a in attempts if a.get("outcome") != "infrastructure"]
    fin = lambda a: a.get("final") or {}
    successful = lambda a: delivery_success(fin(a).get("success", False), a.get("outcome"))
    substantive = [a for a in scored if fin(a).get("substantive")]
    silent = [a for a in substantive if fin(a).get("S")]
    errors = [a for a in substantive if fin(a).get("E")]
    core = [a for a in scored if a["run"]["task_id"] in CORE]
    unans = [a for a in scored if a["run"]["task_id"] in UNANSWERABLE]
    over_abstain = [a for a in core if (a.get("intake") or {}).get("status") == "not_identifiable"]
    completed = [a for a in scored if (a.get("intake") or {}).get("answer_parse") == "ok" and (a.get("intake") or {}).get("memo_present")
                 and a.get("outcome") == "completed"]
    if trap_opportunities is None:
        raise ValueError("trap opportunities are required (load them from the bound gold); an empty map is not a default")
    opps = trap_opportunities
    det_all = app_all = det_done = app_done = 0
    completed_ids = {id(a) for a in completed}
    for a in scored:
        task = a["run"]["task_id"]
        if task not in opps:
            raise ValueError(f"no trap-opportunity metadata for {task}")
        applicable = opps[task]
        found = fin(a).get("traps") or {}
        if set(found) - set(applicable):
            raise ValueError(f"{a['run']['run_id']}: unknown trap keys {sorted(set(found) - set(applicable))}")
        if fin(a).get("status") == "final" and set(found) != set(applicable):
            raise ValueError(f"{a['run']['run_id']}: trap decisions do not cover {sorted(set(applicable) - set(found))}")
        hits = sum(1 for o in applicable if found.get(o) is True)
        det_all, app_all = det_all + hits, app_all + len(applicable)
        if id(a) in completed_ids:
            det_done, app_done = det_done + hits, app_done + len(applicable)
    return {
        "attempts": len(attempts), "infrastructure_reruns_required": infra,
        "trap_recall": _ratio(det_all, app_all), "trap_recall_completed_only": _ratio(det_done, app_done),
        "silent_error_rate": _ratio(len(silent), len(substantive)),                       # NA (None) when no substantive response
        "silent_error_incidence_per_attempt": _ratio(len(silent), len(scored)),
        "conditional_silence_among_errors": _ratio(len(silent), len(errors)),
        "core_accuracy": _ratio(sum(1 for a in core if successful(a)), len(core)),
        "answered_only_accuracy": _ratio(sum(1 for a in core if successful(a) and fin(a).get("substantive")),
                                         sum(1 for a in core if fin(a).get("substantive"))),
        "completion": _ratio(len(completed), len(scored)),
        "valid_abstention": _ratio(sum(1 for a in unans if successful(a)), len(unans)),
        "over_abstention": _ratio(len(over_abstain), len(core)),
        "format_failures": [a["run"]["run_id"] for a in scored if (a.get("intake") or {}).get("answer_parse") not in ("ok", None)],
        "terminal_failures": [a["run"]["run_id"] for a in scored if a.get("outcome") in ("timeout", "error")],
        "per_run": [{"run_id": a["run"]["run_id"], "task_id": a["run"]["task_id"], "outcome": a.get("outcome"),
                     "score": fin(a).get("score"), "success": successful(a), "content_success": fin(a).get("content_success", fin(a).get("success")),
                     "critical": fin(a).get("critical_failure"),
                     "E": fin(a).get("E"), "S": fin(a).get("S"), "substantive": fin(a).get("substantive")} for a in attempts],
    }


def trap_map(root) -> dict[str, list[str]]:
    """Applicable trap opportunities per task, from the bound gold files listed in the gold manifest."""
    import json
    from pathlib import Path
    m = json.loads((Path(root) / "private" / "gold" / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for task, ref in m["gold"].items():
        doc = json.loads((Path(root) / ref["path"]).read_text(encoding="utf-8"))
        if not isinstance(doc.get("trap_opportunities"), list):
            raise ValueError(f"gold {task} has no trap-opportunity metadata")
        out[task] = doc["trap_opportunities"]
    return out
