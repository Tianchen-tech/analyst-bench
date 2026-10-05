"""Orchestration for one attempt: intake -> mapping -> provisional atoms and claims -> provisional record.

A provisional record never carries a final score: `final` is produced only by review.finalize once every pending atom,
claim, critical predicate and cap has an owner decision in the review log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atoms import RULES, atom, map_metrics, metric_claims
from .intake import Intake
from .tasks import FORMAT_ZERO, provisional

CORE = ("Q03", "Q04", "Q07", "Q12", "Q14", "Q16", "Q17")
UNANSWERABLE = ("Q26", "Q27")


def _fixed_key_claims(task: str, intake: Intake, gold: dict[str, Any]) -> list[dict[str, Any]]:
    from .atoms import within
    out = []
    res = intake.answer.get("result") if intake.answer_parse == "ok" and isinstance(intake.answer, dict) else None
    if task == "Q03" and isinstance(res, dict):
        for k in ("gross_usd", "refunds_usd", "net_usd"):
            v = res.get(k)
            out.append({"ref": f"/result/{k}", "kind": "result_value", "text": {k: v}, "mapping": None, "gold": {"value": gold["result"][k]},
                        "auto_verdict": "correct" if within(v, gold["result"][k], "usd") else "wrong"})
    if task == "Q04" and isinstance(res, dict):
        want = {r["platform"]: r for r in gold["result"]["rows"]}
        for i, r in enumerate(res.get("rows") or []):
            key = {"android": "Android", "ios": "iOS"}.get(str(r.get("platform", "")).lower())
            for f, kind in (("eligible", "count"), ("retained", "count"), ("retention", "fraction")):
                g = want.get(key, {}).get(f) if key else None
                out.append({"ref": f"/result/rows/{i}/{f}", "kind": "result_value", "text": {"platform": r.get("platform"), f: r.get(f)},
                            "mapping": None, "gold": {"value": g} if g is not None else None,
                            "auto_verdict": None if g is None else ("correct" if within(r.get(f), g, kind) else "wrong")})
    return out


def _answer_claims(intake: Intake) -> list[dict[str, Any]]:
    if intake.answer_parse != "ok":
        return []
    out = [{"ref": f"/claims/{i}", "kind": "claim", "text": c, "mapping": None, "gold": None, "auto_verdict": None}
           for i, c in enumerate(intake.answer.get("claims", []))]
    res = intake.answer.get("result") or {}
    for key in ("conclusion", "decision", "rationale", "method", "recommendation"):
        if isinstance(res.get(key), str):
            out.append({"ref": f"/result/{key}", "kind": "text", "text": res[key], "mapping": None, "gold": None, "auto_verdict": None})
    for i, d in enumerate(res.get("drivers", []) or []):
        out.append({"ref": f"/result/drivers/{i}", "kind": "driver", "text": d, "mapping": None, "gold": None, "auto_verdict": None})
    for i, f in enumerate(res.get("findings", []) or []):
        out.append({"ref": f"/result/findings/{i}", "kind": "finding", "text": f, "mapping": None, "gold": None, "auto_verdict": None})
    return out


def _warnings_for(intake: Intake, ref: str) -> list[int]:
    """Indices of answer warnings that explicitly link this claim (claim_ids or a result_paths pointer to the value or
    its immediately containing record). Whether the warning QUALIFIES the claim is an owner decision."""
    if intake.answer_parse != "ok":
        return []
    out = []
    for i, w in enumerate(intake.answer.get("warnings", [])):
        paths = w.get("result_paths", [])
        ids = w.get("claim_ids", [])
        cid = None
        if ref.startswith("/claims/"):
            c = intake.answer["claims"][int(ref.split("/")[2])]
            cid = c.get("id")
        rp = ref.replace("/result", "/result", 1)
        hit = (cid is not None and cid in ids) or any(p == rp or (rp.startswith(p + "/") and p.count("/") >= 3) for p in paths)
        if hit:
            out.append(i)
    return out


def build_provisional(run: dict[str, Any], intake: Intake, gold: dict[str, Any], replay: dict[str, Any] | None = None) -> dict[str, Any]:
    task = run["task_id"]
    mapped = map_metrics(task, intake.answer) if intake.answer_parse == "ok" else []
    mclaims, values = metric_claims(task, mapped, gold)
    atoms, flags = provisional(task, intake, gold, mapped, values, replay)
    if intake.answer_parse != "ok":                         # structured numeric atoms cannot be scored from a broken answer
        atoms = [a if not ("values" in a["inputs"] or a["state"] == "auto") or a["atom"].startswith(("q03", "q04"))
                 else atom(a["atom"], a["max"], 0.0, "auto", FORMAT_ZERO) for a in atoms]
    elif task in CORE and intake.status == "not_identifiable":
        atoms = [atom(a["atom"], a["max"], 0.0, "auto", "not_identifiable on an answerable task") if "values" in a["inputs"] or
                 a["state"] == "pending" and "not in structured metrics" in a["reason"] else a for a in atoms]
    claims = _fixed_key_claims(task, intake, gold) + mclaims + _answer_claims(intake)
    for c in claims:
        c["linked_warnings"] = _warnings_for(intake, c["ref"])
    substantive_hint = bool(claims) or intake.memo_words >= 20
    return {"run": run, "rules": RULES, "intake": intake.to_json(), "atoms": atoms, "flags": flags, "claims": claims,
            "metric_mapping": [{"path": m["path"], "mapping": m["mapping"]} for m in mapped],
            "replay": replay, "substantive_hint": substantive_hint,
            "automatic_points": sum(a["awarded"] for a in atoms if a["state"] == "auto"),
            "pending_atoms": [a["atom"] for a in atoms if a["state"] == "pending"],
            "trap_opportunities": list(gold.get("trap_opportunities", [])), "final": None}


def record_digest(record: dict[str, Any]) -> str:
    """SHA-256 of the canonical record without its own digest field (binds atoms, claims, intake hashes and gate)."""
    import hashlib
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def seal(record: dict[str, Any]) -> dict[str, Any]:
    record["record_sha256"] = record_digest(record)
    return record


def load_schema(root: Path, task: str) -> dict[str, Any]:
    return json.loads((Path(root) / "private" / "tasks" / "schemas" / f"{task}.schema.json").read_text(encoding="utf-8"))
