"""Final Pilot-1 results for the four products (ID-49..55): finalize every attempt under both panel versions, aggregate.

    python scripts/final_results.py --dataset generated/pilot

For each version (lenient, strict; ID-55) and each graded attempt of both waves: the scorer's own lineage check and
finalize (evaluation/grader/review.py) with the combined panel log, written beside the provisional record as
final_<version>.json. Then design-5.4 aggregates per product (evaluation/grader/aggregate.py), per-task scores, the
ID-54 speed-adjusted score, time, repetition agreement and run notes. Writes private/results/pilot1_four_products.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from evaluation.grader import aggregate as agg
from evaluation.grader import review as rv
from evaluation.grader.manifest import gate

ROOT = Path(__file__).resolve().parents[1]
WAVES = {"1": ("wave", "wave1"), "2": ("wave2", "wave2")}
VERSIONS = ("lenient", "strict")
PRODUCTS = ["Codex", "Claude Code", "Grok Build", "Antigravity"]
SPEED_BONUS = 0.10                                          # ID-54


def attempts_all() -> list[dict]:
    out = []
    for w, (runs, gdir) in WAVES.items():
        for a in json.loads((ROOT / "private" / "grading" / gdir / "attempts.json").read_text()):
            a = dict(a, wave=w)
            rr = ROOT / "private" / "runs" / runs / "slots"
            rec = next((json.loads(p.read_text()) for p in rr.glob(f"*-{a['slot']['run_id']}/run_record.json")), None)
            a["elapsed"] = (rec or {}).get("elapsed_seconds")
            a["run_record"] = rec
            out.append(a)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    a = ap.parse_args()
    ident = gate(ROOT, a.dataset.resolve())
    salt = rv.salt(ROOT)
    atts = attempts_all()
    result = {"rubric_version": json.loads((ROOT / "private/grading/rubric.json").read_text())["rubric_version"], "versions": {}}
    trap_map = agg.trap_map(ROOT)
    for v in VERSIONS:
        finals = {}
        for att in atts:
            if not att["dir"]:
                continue
            d = Path(att["dir"])
            rec = json.loads((d / "provisional.json").read_text())
            ps = json.loads((d / "packet.json").read_text())["pseudonym"]
            log = json.loads((ROOT / "private" / "review" / "panel" / v / f"{ps}.json").read_text())
            rv.check_lineage(rec, log, ident, d / "archive", salt)        # raises on any mismatch
            gold = json.loads((ROOT / "private" / "gold" / f"{rec['run']['task_id']}.json").read_text())
            fin = rv.finalize(rec, log, gold)
            if fin["status"] != "final":
                raise SystemExit(f"{att['slot']['run_id']} ({v}): not final: {fin.get('missing')}")
            fin["gate"] = ident
            rv.save(d / f"final_{v}.json", fin)
            finals[att["slot"]["run_id"]] = (fin, rec)
        per = {}
        for prod in PRODUCTS:
            mine = [x for x in atts if x["slot"]["product"] == prod]
            items = [{"run": {"run_id": x["slot"]["run_id"], "task_id": x["slot"]["task_id"]}, "outcome": x["outcome"],
                      "intake": finals[x["slot"]["run_id"]][1]["intake"] if x["dir"] else None,
                      "final": finals[x["slot"]["run_id"]][0] if x["dir"] else None} for x in mine]
            ag = agg.aggregate(items, trap_map)
            graded = [x for x in mine if x["dir"]]
            scores = [finals[x["slot"]["run_id"]][0]["score"] for x in graded]
            adj, succ_t, agent_s = [], [], 0.0
            for x in graded:
                f = finals[x["slot"]["run_id"]][0]
                t = float(x["elapsed"] or 1200)
                agent_s += t
                adj.append(f["score"] * (1 + SPEED_BONUS * max(0.0, 1 - t / 1200)) if f["success"] else f["score"])
                if f["success"]:
                    succ_t.append(t)
            per_task = {}
            for x in graded:
                f = finals[x["slot"]["run_id"]][0]
                per_task.setdefault(x["slot"]["task_id"], {})[f"r{x['slot']['repetition']}"] = {
                    "score": round(f["score"], 1), "success": f["success"], "critical": f["critical_failure"], "E": f["E"], "S": f["S"],
                    "elapsed_s": x["elapsed"], "outcome": x["outcome"]}
            same = sum(1 for t in per_task.values() if len(t) == 2 and t["r1"]["success"] == t["r2"]["success"])
            per[prod] = {"aggregate": {k: ag[k] for k in ("core_accuracy", "valid_abstention", "trap_recall", "silent_error_rate",
                                                         "silent_error_incidence_per_attempt", "conditional_silence_among_errors",
                                                         "completion", "over_abstention", "terminal_failures", "format_failures",
                                                         "infrastructure_reruns_required")},
                         "errors_E": sum(finals[x["slot"]["run_id"]][0]["E"] for x in graded),
                         "mean_score": round(sum(scores) / len(scores), 2),
                         "mean_speed_adjusted_score": round(sum(adj) / len(adj), 2),
                         "correct_per_agent_hour": round(len(succ_t) / (agent_s / 3600), 2),
                         "median_seconds_all": statistics.median(float(x["elapsed"] or 1200) for x in graded),
                         "median_seconds_successful": statistics.median(succ_t) if succ_t else None,
                         "total_agent_minutes": round(agent_s / 60, 1), "same_success_both_reps": f"{same}/{len(per_task)}",
                         "per_task": per_task}
        result["versions"][v] = per
    notes = {}
    for x in atts:
        rec = x["run_record"] or {}
        o = rec.get("observed") or {}
        if x["slot"]["product"] == "Antigravity":
            notes.setdefault("antigravity_web_searches", 0)
            notes["antigravity_web_searches"] += o.get("web_search_count") or 0
    result["notes"] = notes
    out = ROOT / "private" / "results" / "pilot1_four_products.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"written": str(out.relative_to(ROOT))}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
