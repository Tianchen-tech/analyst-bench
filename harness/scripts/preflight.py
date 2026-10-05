"""Pilot-1 preflight (design Phase 6, ID-43/44): real product runs on the TOY tasks only, excluded from scoring.

    python scripts/preflight.py check                 # prerequisites only (no product run, no quota used)
    python scripts/preflight.py smoke  [--product P]  # one toy1 run per product: observe identity, egress, usage
    python scripts/preflight.py runs                  # the eight runs: 2 products x toy1/toy2 x 2 repetitions
    python scripts/preflight.py checks                # per product: one forced timeout (8 s cap) and one blocked-access run
    ... --wave 2                                      # wave 2 products (Grok Build, Gemini CLI; ID-49)

Outputs go to private/runs/preflight/<stage>-<UTC time>/ (git-ignored; every file is hash-recorded in its run record).
Runs use the owner's subscription allowance; nothing is purchased. A usage-limit signal stops the stage (ID-43).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from runners import controller as ctl

ROOT = ctl.PROJECT_ROOT
TOY = ROOT / "private" / "runners" / "toy" / "tasks"
WAVES = {"1": ["Codex", "Claude Code"], "2": ["Grok Build", "Antigravity"]}      # wave 2: ID-49
WAVE = sys.argv[sys.argv.index("--wave") + 1] if "--wave" in sys.argv else "1"
ORDER = WAVES[WAVE]
CREDENTIAL = {"codex_exec": "auth.json", "claude_code_print": "oauth_token", "grok_build": "auth.json", "antigravity_cli": ".gemini/antigravity-cli/antigravity-oauth-token"}


def prerequisites() -> dict[str, object]:
    cfg = ctl.config()
    out = {}
    for name, spec in ((n, cfg["products"][n]) for n in ORDER):
        base = (ROOT / spec["profile_baseline"]).resolve()
        cred = base / CREDENTIAL[spec["adapter"]]
        binary = Path(spec["binary"]) if Path(spec["binary"]).is_absolute() else ROOT / spec["binary"]
        out[name] = {"binary_present": binary.is_file(), "credential_present": cred.is_file(), "credential_path": str(cred)}
    out["toy_tasks_present"] = all((TOY / t / f).is_file() for t in ("toy1", "toy2", "toy3") for f in ("task.md", "game.duckdb"))
    return out


def toy_check(rec: dict, out: Path, toy: str) -> dict[str, object]:
    gold = json.loads((TOY / "toy_gold.json").read_text())
    try:
        ans = json.loads((out / "outputs" / "answer.json").read_text())
    except (OSError, ValueError):
        return {"answer": "missing or invalid"}
    if toy == "toy1":
        r = ans.get("result") or {}
        g = gold["TOY1"]
        return {"total_ok": abs(float(r.get("total_usd", -1)) - g["total_usd"]) <= 0.01, "payers_ok": r.get("payers") == g["payers"],
                "sql_saved": "toy1.sql" in rec["output_hashes"]}
    if toy == "toy2":
        return {"not_identifiable": ans.get("status") == "not_identifiable"}
    return {}


def run(product: str, toy: str, rep: int, stage_dir: Path, limit: float | None = None, tag: str = "") -> dict:
    out = stage_dir / f"{ctl.config()['products'][product]['adapter']}-{toy}-r{rep}{tag}"
    rec = ctl.run_slot(product, TOY / toy, out, {"run_id": out.name, "task_id": toy.upper(), "repetition": rep,
                                                "excluded_from_scoring": True}, time_limit_s=limit)
    summary = {"run": out.name, "product": product, "outcome": rec["outcome_status"], "stop": rec["stop_reason"],
               "elapsed_s": rec["elapsed_seconds"], "models": rec["observed"].get("models_in_session") or rec["observed"].get("models_in_transcript"),
               "efforts": rec["observed"].get("efforts_in_session") or rec["observed"].get("per_turn_effort_active"),
               "quota": rec["observed"].get("quota"), "usage": rec["usage"],
               "background_denied": len(rec["egress"].get("denied_product_background", [])),
               "egress_allowed": rec["egress"]["allowed"], "egress_denied": [d["target"] for d in rec["egress"]["denied"]],
               "canary_passed": rec["canary_check"]["passed"], "database_unchanged": rec["database_unchanged"],
               "availability": rec["availability_signals"][:3], "toy": toy_check(rec, out, toy) if rec["outcome_status"] == "completed" else None}
    print(json.dumps(summary), flush=True)
    return summary


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "check"
    pre = prerequisites()
    if stage == "check":
        print(json.dumps(pre, indent=1))
        return 0
    only = sys.argv[sys.argv.index("--product") + 1] if "--product" in sys.argv else None
    products = [p for p in ORDER if only in (None, p)]
    missing = [p for p in products if not (pre[p]["binary_present"] and pre[p]["credential_present"])]
    if missing or not pre["toy_tasks_present"]:
        print(f"REFUSED: prerequisites missing for {missing or 'toy tasks'}: {json.dumps(pre)}", file=sys.stderr)
        return 2
    stage_dir = ROOT / "private" / "runs" / ("preflight" if WAVE == "1" else f"preflight-wave{WAVE}") / f"{stage}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    stage_dir.mkdir(parents=True)
    results = []
    plan = {"smoke": [(p, "toy1", 1, None, "") for p in products],
            "runs": [(p, toy, rep, None, "") for rep in (1, 2) for j, toy in enumerate(("toy1", "toy2"))
                     for p in (products if (rep + j) % 2 == 0 else products[::-1])],          # alternate product order per block
            "checks": [x for p in products for x in ((p, "toy1", 1, 8, "-forced-timeout"), (p, "toy3", 1, None, "-blocked-access"))]}[stage]
    for product, toy, rep, limit, tag in plan:
        s = run(product, toy, rep, stage_dir, limit, tag)
        results.append(s)
        if s["outcome"] == "availability_limit":
            print("STOPPED: availability/usage-limit signal; wait for the provider's reset before continuing (ID-43)", file=sys.stderr)
            break
    (stage_dir / "summary.json").write_text(json.dumps(results, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
