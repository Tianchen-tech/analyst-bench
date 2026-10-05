"""Assemble the Pilot-1 run bundle (contract pilot1-bundle-v2) from the frozen artifacts and a real toy preflight.

    python scripts/assemble_run_bundle.py --dataset generated/pilot --runs private/runs/preflight/runs-<UTC> \
        --checks private/runs/preflight/checks-<UTC> [--wave 2]

Every product identity is taken from the controller's own run records, never from the agent's self-description; the
bundle summaries are copied from those records and the validator reads the records back. Writes
private/run_bundle/{manifest.json, isolation_policy.json, failure_policy.json, settings/*.json, budget/*.json} and runs
the bundle check. The preflight evidence stays in private/runs/ (git-ignored) and is bound by hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from evaluation import run_bundle as rb
from generator import tasks
from generator.export_duckdb import file_sha256

ROOT = Path(__file__).resolve().parents[1]
TOY = "private/runners/toy/tasks"
TOYS = [("toy1", "numeric_file_output"), ("toy2", "incomplete_data")]
BUDGET_SOURCE = {"1": "private/design/reviews/PILOT1_SUBSCRIPTION_ONLY_DECISION_2026-10-03.md",
                 "2": "private/design/reviews/PILOT1_WAVE2_BUDGET_2026-10-04.md"}
PLANS = {"Codex": "ChatGPT Plus", "Claude Code": "Claude Pro", "Grok Build": "grok.com subscription", "Antigravity": "Google AI Pro"}
SCHEDULE_SEED = 20260931
ORDER = rb.WAVES["1"]["products"]                          # replaced by the wave's products in main()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def ref(p: Path) -> dict[str, str]:
    return {"path": rel(p), "sha256": sha(p)}


def write(p: Path, doc: dict) -> dict[str, str]:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return ref(p)


def schedule(order: list[str] | None = None) -> list[dict]:
    """Design 6.5 / 9.1: seed 20260931; tasks shuffled within each repetition (SHA-256 keyed order, no process RNG);
    one block per task x repetition holding both products; product order alternates by block in r1 and is reversed per
    task in r2, so every task has each product first once and each product goes first in 9 of the 18 blocks."""
    ORDER = order or rb.WAVES["1"]["products"]
    slots, first_r1 = [], {}
    for r in (1, 2):
        order = sorted(tasks.PILOT_TASKS, key=lambda t: hashlib.sha256(f"{SCHEDULE_SEED}|pilot1-schedule|r{r}|{t}".encode()).hexdigest())
        for k, t in enumerate(order):
            if r == 1:
                first_r1[t] = ORDER[k % 2]
                pair = [ORDER[k % 2], ORDER[(k + 1) % 2]]
            else:
                pair = [p for p in ORDER if p != first_r1[t]] + [first_r1[t]]
            for i, p in enumerate(pair):
                slots.append({"order": len(slots), "block": f"r{r}-{t}", "position_in_block": i, "product": p, "task": t,
                              "repetition": r})
    return slots


def records(stage: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(stage.glob("*/run_record.json")):
        out[f.parent.name] = json.loads(f.read_text(encoding="utf-8"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--checks", type=Path, required=True)
    ap.add_argument("--wave", default="1", choices=sorted(rb.WAVES))
    args = ap.parse_args()
    OUT = ROOT / rb.WAVES[args.wave]["dir"]
    products_spec = rb.wave_products(args.wave)
    canon = rb.canonical(args.wave)
    runs_dir, checks_dir = (ROOT / args.runs).resolve(), (ROOT / args.checks).resolve()
    cfg = json.loads((ROOT / "private/runners/products.json").read_text(encoding="utf-8"))
    run_recs, check_recs = records(runs_dir), records(checks_dir)

    isolation = write(OUT / "isolation_policy.json", {
        **rb.ISOLATION_FIXED,
        "boundary": "macOS sandbox-exec on the owner's Mac, one fresh run root per run (ID-44, owner-confirmed 2026-10-03)",
        "file_reads": "system locations, the product install, the common analysis environment and the run root only",
        "file_writes": "the run root only (work/, home/, tmp/)",
        "network_detail": "only the controller's allowlist proxy on 127.0.0.1; HTTPS CONNECT to the product's inference and "
                          "authentication hosts; everything else denied and logged",
        "profile": "a per-run copy of a clean authenticated product profile; no user settings, rules, MCP servers or memory",
        "known_limits": ["one shared host kernel", "the owner's machine, not a disposable VM",
                         "descendants that re-parent are tracked by polling"],
        **({"product_exceptions": {
            "Antigravity": ["localhost network (bind/inbound/outbound) and /dev/ptmx for its language server and terminal (ID-52); "
                            "other local services must be stopped during the wave",
                            "server-side web search (search_web) cannot be disabled; every query is recorded (ID-53)"],
            "Grok Build": ["product background requests (grok.com, api.mixpanel.com, api.x.ai) denied and recorded apart"]}}
           if args.wave == "2" else {})})
    failure = write(OUT / "failure_policy.json", {
        **rb.FAILURE_FIXED,
        "replacement_for_infrastructure_failures": "one replacement attempt in a new sandbox, at least 30 minutes after a "
                                                   "service failure; both records kept and the original labelled (design 6.5)",
        "availability_limit": "subscription quota exhaustion is an availability event, not an analysis error: stop "
                              "initiating runs, wait for the provider's reset, keep the event and apply the replacement "
                              "rule above; never resume the analytical conversation (ID-43)",
        "no_replacement": ["clarification request", "noncompliant format", "recoverable tool error", "timeout", "refusal",
                           "empty or poor output"],
        "settings_change": "a forced product update or model change stops that product; the boundary is recorded and the "
                           "wave restarts under a new bundle; changed versions are never pooled"})

    products, bound = [], {}
    approval_src = ROOT / BUDGET_SOURCE[args.wave]
    for name, spec in products_spec.items():
        pc = cfg["products"][name]
        mine = {k: r for k, r in run_recs.items() if r["product_name"] == name}
        if len(mine) != 4:
            raise SystemExit(f"{name}: expected 4 preflight runs in {runs_dir}, found {len(mine)}")
        first = min(mine.values(), key=lambda r: r["started_at_utc"])
        idents = {json.dumps(r["identity"], sort_keys=True) for r in mine.values()}
        snaps = {r["settings_snapshot_sha256"] for r in mine.values()}
        models = set().union(*({*(r["observed"].get("models_in_session") or []), *(r["observed"].get("models_in_transcript") or [])}
                               for r in mine.values()))
        served = set(pc.get("served_model_aliases") or [])
        if len(idents) != 1 or len(snaps) != 1 or pc["model"] not in models or not models <= {pc["model"], *served}:
            raise SystemExit(f"{name}: identity, settings snapshot or model not constant across runs: {models}")
        ident = first["identity"]
        if name == "Codex":
            efforts = set().union(*(set(r["observed"].get("efforts_in_session") or []) for r in mine.values()))
            effort_note = f"session rollouts report effort {sorted(efforts)}"
            sources = ["version_command", "session_metadata", "settings"]
            permissions = ["Codex approvals and sandbox bypassed (--dangerously-bypass-approvals-and-sandbox) inside the "
                           "controller's sandbox-exec boundary", "user config and rules ignored", "web search disabled"]
        elif name == "Grok Build":
            effort_note = f"requested --reasoning-effort {pc['reasoning_effort']}; served model ids {sorted(models)}; level not echoed"
            sources = ["version_command", "session_metadata", "settings"]
            permissions = ["always-approve tool execution inside the controller's sandbox-exec boundary",
                           "disallowed tools: " + ", ".join(pc["disallowed_tools"]), "web search disabled (--disable-web-search)",
                           "subagents at the product default", "fresh GROK_HOME (credentials and bundled resources only)"]
        elif name == "Antigravity":
            effort_note = f"model id {pc['model']} carries the High level (CLI model list: 'Gemini 3.8 Flash (High)')"
            sources = ["version_command", "session_metadata", "settings"]
            permissions = ["toolPermission always-proceed", "deny: " + ", ".join(pc["permission_deny"]),
                           "search_web not controllable (ID-53)", "telemetry and paid credits off", "subagents at the product default",
                           "fresh HOME (OAuth token, onboarding and project state, benchmark settings only)"]
        else:
            active = {r["observed"].get("per_turn_effort_active") for r in mine.values()}
            effort_note = f"requested --effort {pc['reasoning_effort']}; product reports per-turn effort active {sorted(map(str, active))}; level not echoed"
            sources = ["version_command", "session_metadata", "settings"]
            permissions = ["permission mode acceptEdits", "allowed tools: " + ", ".join(pc["frozen_tool_allowlist"]),
                           "disallowed tools: " + ", ".join(pc["disallowed_tools"]), "native subagents at the product default",
                           "no setting sources, strict empty MCP config, no session persistence"]
        permissions += ["file reads: system, product install, analysis environment, run root",
                        "file writes: run root only", "network: allowlist proxy only"]
        observed = {"product_version": ident["version_command"], "executable_sha256": ident["executable_sha256"],
                    "interface": "cli", "model_provider": spec["provider"], "model_display_name": pc["model"],
                    "reasoning_setting": pc["reasoning_effort"], "reasoning_observation": effort_note,
                    "model_selection_source": ident["model_selection_source"], "observation_sources": sources,
                    "observed_at_utc": first["started_at_utc"],
                    "observed_in": sorted(rel(runs_dir / k / "run_record.json") for k in mine),
                    **({"served_model_aliases": sorted(served)} if served else {})}
        settings = {"permission_map": permissions, "network_allowlist": pc["egress_allowlist"],
                    "web_search_disabled": name != "Antigravity",
                    **({"web_search_exception": "ID-53: Antigravity's server-side search_web cannot be disabled; owner accepted with disclosure; queries recorded"}
                       if name == "Antigravity" else {}),
                    "benchmark_overrides": pc["benchmark_overrides"], "runtime_settings_snapshot_sha256": snaps.pop(),
                    "runtime_settings_snapshot": first["settings_snapshot"]}
        snap = write(OUT / "settings" / f"{spec['adapter']}.json",
                     {"product": name, "adapter": spec["adapter"], "observed": observed, "settings": settings})
        approval = write(OUT / "budget" / f"{spec['adapter']}.json", {
            "decision": "approved", "ceiling_usd": 0, "product": name,
            "approved_by": "owner (direct instruction in chat, " + ("2026-10-03" if args.wave == "1" else "2026-10-04") + ")",
            "scope": "existing subscription allowance only (" + PLANS[name] + "); no "
                     "purchases, extra usage, upgrades, automatic reload or API billing; quota exhaustion pauses scheduling",
            "source": {"path": BUDGET_SOURCE[args.wave], "sha256": sha(approval_src)}})
        adapter = ROOT / spec["adapter_path"]
        bound[name] = (sha(adapter), snap["sha256"])
        products.append({"name": name, "adapter": spec["adapter"], "adapter_artifact": ref(adapter),
                         "observed": dict(observed, settings_snapshot=snap), "settings": settings,
                         "budget": {"decision": "approved", "ceiling_usd": 0, "approval": approval}})

    toys = [{"id": t, "kind": kind, "task_md": ref(ROOT / TOY / t / "task.md"), "database": ref(ROOT / TOY / t / "game.duckdb")}
            for t, kind in TOYS]
    pre_runs = []
    for key, r in sorted(run_recs.items()):
        d = runs_dir / key
        st = r["staging"]
        pre_runs.append({"product": r["product_name"], "toy_task": r["run"]["task_id"].lower(), "repetition": r["run"]["repetition"],
                         "run_id": r["run"]["run_id"], "excluded_from_scoring": True, "outcome_status": r["outcome_status"],
                         "stop_reason": r["stop_reason"], "elapsed_seconds": r["elapsed_seconds"], "usage": r["usage"],
                         "transcript": ref(d / "transcript.jsonl"), "run_record": ref(d / "run_record.json"),
                         "reset_evidence": ref(d / "run_record.json"), "start_listing": st["listing"],
                         "db_sha256_before": st["database_sha256"],
                         "db_sha256_after": st["database_sha256"] if r["database_unchanged"] else None,
                         "adapter_sha256": bound[r["product_name"]][0], "settings_snapshot_sha256": bound[r["product_name"]][1]})
    checks = []
    for key, r in sorted(check_recs.items()):
        d, name = checks_dir / key, r["product_name"]
        kind = "forced_timeout" if key.endswith("-forced-timeout") else "blocked_access" if key.endswith("-blocked-access") else None
        if kind is None:
            continue
        base = {"product": name, "check": kind, "run_id": r["run"]["run_id"], "transcript": ref(d / "transcript.jsonl"),
                "run_record": ref(d / "run_record.json"), "evidence": ref(d / "egress.jsonl"),
                "adapter_sha256": bound[name][0], "settings_snapshot_sha256": bound[name][1]}
        if kind == "forced_timeout":
            ok = r["stop_reason"] == "timeout" and r["processes_left_after_kill"] == 0
            checks.append({**base, "passed": ok, "cap_seconds": int(r["time_limit_s"]), "stopped_at_seconds": r["elapsed_seconds"],
                           "child_processes_remaining": r["processes_left_after_kill"]})
        else:
            denied = r["egress"]["denied"]
            allowed_hosts = {a.rpartition(":")[0] for a in r["egress"]["allowed"]}
            content = not allowed_hosts <= set(cfg["products"][name]["egress_allowlist"])
            checks.append({**base, "passed": bool(denied) and not content, "denied_requests": len(denied),
                           "denied_targets": sorted({x["target"] for x in denied}), "content_obtained": content})

    arts = {k: ref(ROOT / p) for k, p in canon.items() if k not in ("isolation_policy", "failure_policy")}
    arts["isolation_policy"], arts["failure_policy"] = isolation, failure
    bundle = {"contract": rb.CONTRACT, "pilot": "Pilot-1", "wave": args.wave, "products": products, "tasks": list(tasks.PILOT_TASKS),
              "repetitions": rb.REPETITIONS, "time_limit_seconds": rb.TIME_LIMIT,
              "schedule_rule": {"seed": SCHEDULE_SEED, "doc": schedule.__doc__.strip().replace("\n    ", " "),
                                "run_window": "both products of a block within 24 hours where quota allows; r1 and r2 on "
                                              "different days where feasible; subscription quota pauses are recorded"},
              "slots": schedule(rb.WAVES[args.wave]["products"]), "preflight": {"toy_tasks": toys, "runs": pre_runs, "adapter_checks": checks},
              "runner": {k: ref(ROOT / p) for k, p in rb.RUNNER.items()}, "artifacts": arts,
              "database_sha256": file_sha256(args.dataset / "game.duckdb")}
    (OUT / "manifest.json").write_text(json.dumps(bundle, indent=1) + "\n", encoding="utf-8")
    ok, detail = rb.check(ROOT, args.dataset, args.wave)
    print(json.dumps({"bundle": rel(OUT / "manifest.json"), "sha256": sha(OUT / "manifest.json"), "valid": ok, "problems": detail}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
