"""Pilot-1 run-bundle contract, `pilot1-bundle-v2` (public-definitions review §5, 2026-10-02; runner binding, ID-45).

The bundle (private/run_bundle/manifest.json) is checked by structure and by the identity of what it references, never by
the truthiness of its fields. Every referenced file is an artifact reference {"path", "sha256"}: a relative POSIX path
inside the project root with no `..`, no absolute prefix and no symlinked component, naming a regular file whose bytes
hash to the recorded value. Required references sit at canonical paths, so a text file renamed as a dependency is not that
dependency. Contract (design 6.1-6.5, Section 8 Pilot-1, Phase 6):

  products       exactly Codex and Claude Code; adapter ID, canonical adapter file declaring that ID, controller-observed
                 identity (version, executable hash, CLI interface, first-party provider, model, reasoning setting,
                 selection source, observation sources, settings snapshot), frozen settings (permission map, network
                 allowlist, web search disabled, declared overrides) and an approved budget decision with a ceiling.
  schedule       the nine tasks x two products x two repetitions: 36 unique slots, positions 0..35 once each.
  preflight      two toy tasks (one numeric/file-output, one incomplete-data) on a toy database distinct from the
                 production one; the eight distinct product x toy task x repetition runs, each excluded from scoring and
                 carrying its outcome, elapsed time within the limit, usage record, transcript and reset evidence, the
                 exact two-file starting listing, unchanged toy-database hash and the adapter/settings hashes in force;
                 per adapter one forced-timeout check (process tree stopped) and one blocked-access check (denied, no content).
  policies       isolation and failure policies as hash-verified JSON documents with the protocol's fixed values.
  policy         the frozen grading-policy record (private/freeze/grading_policy.json) must pass check_policy with the
                 record hash the grader manifest binds; the grader's `code` is the implementation manifest
                 (private/grading/implementation.json), every listed scoring module must match its hash on disk.
  dependencies   the task export manifest, schema catalog and definitions approval at their canonical paths, and the
                 database, all equal to the certified package; the Pilot-1 freeze record, which must still match
                 (evaluation/freeze.py); a gold manifest bound to those same versions and to the freeze record whose per-task
                 gold validates against the task schema; a grader bound to that gold manifest and to a versioned rubric,
                 whose replay report names the exact grader code, rubric and gold manifest it tested and whose case
                 results equal the manifest's, all passed.
  Version binding (review of 2026-10-02): the settings snapshot's content must equal the declared observed identity and
  settings, and every preflight run and adapter check carries that snapshot's hash, so changed settings invalidate the
  old preflight.
  Runner binding (v2, ID-45): the bundle references the runner code and configuration (controller, proxy, shared adapter
  helpers, products.json) at canonical paths, and every preflight run and adapter check references the controller's own
  run record. The record is read and must agree with the bundle: the runner files and adapter hashes it ran under, the
  runtime settings-snapshot hash declared in the product settings, the executable hash and version, the model observed
  (for the eight runs), the fresh two-file staging, the toy database, the canary, times, stop reason and transcript hash.
  A preflight from an earlier runner or setting therefore cannot certify the current one, and the bundle's own
  summaries cannot overstate what the controller recorded. products.json must declare the same model, effort and
  allowlist as the product record.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT = "pilot1-bundle-v2"
TIME_LIMIT = 1200
REPETITIONS = 2
WORK_DIR_FILES = ["game.duckdb", "task.md"]
ALL_PRODUCTS = {
    "Codex": {"adapter": "codex_exec", "provider": "OpenAI", "adapter_path": "private/runners/adapters/codex_exec.py"},
    "Claude Code": {"adapter": "claude_code_print", "provider": "Anthropic",
                    "adapter_path": "private/runners/adapters/claude_code_print.py"},
    "Grok Build": {"adapter": "grok_build", "provider": "xAI", "adapter_path": "private/runners/adapters/grok_build.py"},
    "Antigravity": {"adapter": "antigravity_cli", "provider": "Google", "adapter_path": "private/runners/adapters/antigravity_cli.py"},
}
WAVES = {"1": {"products": ["Codex", "Claude Code"], "dir": "private/run_bundle"},                 # Pilot-1 wave 1
         "2": {"products": ["Grok Build", "Antigravity"], "dir": "private/run_bundle/wave2"}}       # ID-49/52
PRODUCTS = {n: ALL_PRODUCTS[n] for n in WAVES["1"]["products"]}


def wave_products(wave: str) -> dict[str, dict[str, str]]:
    return {n: ALL_PRODUCTS[n] for n in WAVES[wave]["products"]}


def canonical(wave: str) -> dict[str, str]:
    """Shared artifacts plus the wave's own isolation and failure policies (in the wave's bundle directory)."""
    d = WAVES[wave]["dir"]
    return {**CANONICAL, "isolation_policy": f"{d}/isolation_policy.json", "failure_policy": f"{d}/failure_policy.json"}
TOY_KINDS = {"numeric_file_output", "incomplete_data"}
OBSERVATION_SOURCES = {"version_command", "settings", "session_metadata", "screenshot"}
CANONICAL = {"task_export_manifest": "private/tasks/export/manifest.json",
             "schemas_catalog": "private/tasks/schemas/catalog.json",
             "definitions_approval": "private/release/public_definitions.approval.json",
             "gold_manifest": "private/gold/manifest.json",
             "grader": "private/grading/grader_manifest.json",
             "isolation_policy": "private/run_bundle/isolation_policy.json",
             "failure_policy": "private/run_bundle/failure_policy.json",
             "data_freeze": "private/freeze/pilot1_freeze.json",
             "grading_policy": "private/freeze/grading_policy.json"}
GRADER_IMPLEMENTATION = "private/grading/implementation.json"
RUNNER = {"controller": "private/runners/controller.py", "proxy": "private/runners/proxy.py",
          "adapter_common": "private/runners/adapters/_common.py", "products": "private/runners/products.json"}
ISOLATION_FIXED = {"kind": "isolation_policy", "work_dir_files": WORK_DIR_FILES, "database_read_only": True,
                   "reset": "every_run", "network": "inference_endpoints_only", "private_repository_mounted": False,
                   "canary_check": True}
FAILURE_FIXED = {"kind": "failure_policy", "time_limit_seconds": TIME_LIMIT, "replacement_for_agent_failures": False,
                 "post_run_repair": False, "resume_allowed": False, "both_repetitions_counted": True}
REPLAY_CASES = {"correct_answer_fabricated_memo", "wrong_answer_relevant_warning", "wrong_answer_unrelated_boilerplate",
                "pure_refusal", "malformed_json_substantive_memo", "empty_timeout", "sql_replay_path_traversal",
                "code_network_access", "script_reads_truth"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class _Refs:
    """Resolves and verifies artifact references; every failure is recorded, never raised."""

    def __init__(self, root: Path, problems: list[str]):
        self.root, self.problems = root.resolve(), problems

    def path(self, ref: Any, label: str, canonical: str | None = None) -> Path | None:
        if not isinstance(ref, dict) or not _str(ref.get("path")) or not HEX64.match(str(ref.get("sha256", ""))):
            self.problems.append(f"{label}: not an artifact reference {{path, sha256}}")
            return None
        rel = ref["path"]
        pure = PurePosixPath(rel)
        if pure.is_absolute() or "\\" in rel or ".." in pure.parts or rel.startswith("~"):
            self.problems.append(f"{label}: path must be relative and inside the project ({rel})")
            return None
        if canonical is not None and rel != canonical:
            self.problems.append(f"{label}: must reference {canonical}, not {rel}")
            return None
        p, cur = self.root, self.root
        for part in pure.parts:
            cur = cur / part
            if cur.is_symlink():
                self.problems.append(f"{label}: symlinked path component {part}")
                return None
        p = cur
        if not p.resolve().is_relative_to(self.root) or not p.is_file():
            self.problems.append(f"{label}: not a regular file inside the project ({rel})")
            return None
        if _sha(p) != ref["sha256"]:
            self.problems.append(f"{label}: hash mismatch")
            return None
        return p

    def json(self, ref: Any, label: str, canonical: str | None = None) -> dict[str, Any] | None:
        p = self.path(ref, label, canonical)
        if p is None:
            return None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            self.problems.append(f"{label}: not JSON")
            return None
        if not isinstance(doc, dict):
            self.problems.append(f"{label}: not a JSON object")
            return None
        return doc


def _fixed(doc: dict[str, Any] | None, fixed: dict[str, Any], label: str, problems: list[str]) -> None:
    if doc is None:
        return
    for k, v in fixed.items():
        got = sorted(doc.get(k)) if isinstance(v, list) and isinstance(doc.get(k), list) else doc.get(k)
        if got != v:
            problems.append(f"{label}.{k} must be {v!r}")


def _runner(bundle: dict[str, Any], refs: _Refs, problems: list[str]) -> tuple[dict[str, str], dict[str, Any] | None]:
    """The runner files at their canonical paths; returns {path: sha256} and the parsed products.json."""
    run = bundle.get("runner") if isinstance(bundle.get("runner"), dict) else {}
    files, cfg = {}, None
    for k, rel in RUNNER.items():
        p = refs.path(run.get(k), f"runner {k}", rel)
        if p is not None:
            files[rel] = run[k]["sha256"]
            if k == "products":
                cfg = _load(p)
    return files, cfg if isinstance(cfg, dict) else None


def _products(bundle: dict[str, Any], refs: _Refs, problems: list[str], cfg: dict[str, Any] | None = None,
              PRODUCTS: dict[str, dict[str, str]] = PRODUCTS) -> dict[str, dict[str, str]]:
    """Validate the two product records; return per-product {adapter_sha256, settings_snapshot_sha256,
    runtime_settings_snapshot_sha256}."""
    products = bundle.get("products")
    if not isinstance(products, list) or sorted(p.get("name") for p in products if isinstance(p, dict)) != sorted(PRODUCTS) \
            or len(products) != len(PRODUCTS):
        problems.append(f"products must be exactly {sorted(PRODUCTS)}")
        return {}
    bound: dict[str, dict[str, str]] = {}
    for p in products:
        name, spec = p["name"], PRODUCTS[p["name"]]
        lab = f"product {name}"
        if p.get("adapter") != spec["adapter"]:
            problems.append(f"{lab}: adapter must be {spec['adapter']}")
        adapter = refs.path(p.get("adapter_artifact"), f"{lab} adapter", spec["adapter_path"])
        if adapter is not None and not re.search(rf'^ADAPTER_ID = "{spec["adapter"]}"$', adapter.read_text(encoding="utf-8"), re.M):
            problems.append(f"{lab}: adapter file does not declare ADAPTER_ID {spec['adapter']}")
        obs = p.get("observed") if isinstance(p.get("observed"), dict) else {}
        for k in ("product_version", "model_display_name", "reasoning_setting", "observed_at_utc"):
            if not _str(obs.get(k)):
                problems.append(f"{lab}: observed.{k} missing")
        if not HEX64.match(str(obs.get("executable_sha256", ""))):
            problems.append(f"{lab}: observed.executable_sha256 must be a SHA-256")
        if obs.get("interface") != "cli":
            problems.append(f"{lab}: observed.interface must be cli")
        if obs.get("model_provider") != spec["provider"]:
            problems.append(f"{lab}: observed.model_provider must be the first-party provider {spec['provider']}")
        if obs.get("model_selection_source") not in ("default", "explicit"):
            problems.append(f"{lab}: observed.model_selection_source must be default or explicit")
        src = obs.get("observation_sources")
        if not isinstance(src, list) or not src or not set(src) <= OBSERVATION_SOURCES:
            problems.append(f"{lab}: observed.observation_sources must be a nonempty subset of {sorted(OBSERVATION_SOURCES)}")
        st = p.get("settings") if isinstance(p.get("settings"), dict) else {}
        snapshot = refs.path(obs.get("settings_snapshot"), f"{lab} settings snapshot")
        if snapshot is not None:
            snap = _load(snapshot)
            declared = {"product": name, "adapter": spec["adapter"],
                        "observed": {k: v for k, v in obs.items() if k != "settings_snapshot"}, "settings": st}
            if snap != declared:
                problems.append(f"{lab}: settings snapshot content differs from the declared identity and settings in force")
                snapshot = None
        if not isinstance(st.get("permission_map"), list) or not st["permission_map"] or not all(_str(x) for x in st["permission_map"]):
            problems.append(f"{lab}: settings.permission_map must list the frozen permissions")
        if not isinstance(st.get("network_allowlist"), list) or not st["network_allowlist"] or not all(_str(x) for x in st["network_allowlist"]):
            problems.append(f"{lab}: settings.network_allowlist must list the inference endpoints")
        if st.get("web_search_disabled") is not True and not (st.get("web_search_disabled") is False and _str(st.get("web_search_exception"))):
            problems.append(f"{lab}: settings.web_search_disabled must be true (or false with a documented web_search_exception, ID-53)")
        if not isinstance(st.get("benchmark_overrides"), list) or not all(_str(x) for x in st["benchmark_overrides"]):
            problems.append(f"{lab}: settings.benchmark_overrides must be a list of declared overrides")
        if not HEX64.match(str(st.get("runtime_settings_snapshot_sha256", ""))):
            problems.append(f"{lab}: settings.runtime_settings_snapshot_sha256 must be the controller's settings-snapshot hash")
        if cfg is not None:
            pc = (cfg.get("products") or {}).get(name) if isinstance(cfg.get("products"), dict) else None
            if not isinstance(pc, dict) or pc.get("adapter") != spec["adapter"] or pc.get("model") != obs.get("model_display_name") \
                    or pc.get("reasoning_effort") != obs.get("reasoning_setting") or pc.get("egress_allowlist") != st.get("network_allowlist") \
                    or cfg.get("time_limit_s") != TIME_LIMIT:
                problems.append(f"{lab}: products.json does not declare this adapter, model, effort, allowlist and time limit")
        bud = p.get("budget") if isinstance(p.get("budget"), dict) else {}
        if bud.get("decision") != "approved" or not _num(bud.get("ceiling_usd")) or bud["ceiling_usd"] < 0:
            problems.append(f"{lab}: budget must be an approved decision with a nonnegative ceiling_usd")
        approval = refs.json(bud.get("approval"), f"{lab} budget approval")
        if approval is not None and (approval.get("decision") != "approved" or approval.get("ceiling_usd") != bud.get("ceiling_usd")
                                     or approval.get("product") != name or not _str(approval.get("approved_by"))):
            problems.append(f"{lab}: budget approval record does not match the decision")
        if adapter is not None and snapshot is not None:
            bound[name] = {"adapter_sha256": _sha(adapter), "settings_snapshot_sha256": _sha(snapshot),
                           "runtime_settings_snapshot_sha256": st.get("runtime_settings_snapshot_sha256"),
                           "adapter_path": spec["adapter_path"], "adapter": spec["adapter"],
                           "executable_sha256": obs.get("executable_sha256"), "product_version": obs.get("product_version"),
                           "model": obs.get("model_display_name"),
                           "served_aliases": [a for a in (obs.get("served_model_aliases") or []) if isinstance(a, str)]}
    return bound


def _schedule(bundle: dict[str, Any], tasks: tuple[str, ...], problems: list[str], PRODUCTS: dict[str, Any] = PRODUCTS) -> None:
    if bundle.get("tasks") != list(tasks) or bundle.get("repetitions") != REPETITIONS:
        problems.append("tasks or repetitions")
    slots = bundle.get("slots")
    if not isinstance(slots, list) or not all(isinstance(s, dict) for s in slots):
        problems.append("slots must be a list of slot records")
        return
    grid = {(p, t, r) for p in PRODUCTS for t in tasks for r in range(1, REPETITIONS + 1)}
    keys = [(s.get("product"), s.get("task"), s.get("repetition")) for s in slots]
    if set(keys) != grid or len(keys) != len(grid):
        problems.append("schedule must cover the 36 unique product x task x repetition slots once each")
    if sorted(s.get("order") for s in slots if isinstance(s.get("order"), int)) != list(range(len(grid))):
        problems.append("slot positions must be 0..35, each once")
    if bundle.get("time_limit_seconds") != TIME_LIMIT:
        problems.append("time limit")


def _record(entry: dict[str, Any], refs: _Refs, bound: dict[str, dict[str, str]], runner: dict[str, str], lab: str,
            problems: list[str]) -> dict[str, Any] | None:
    """Read the controller's run record for one preflight run or adapter check and verify it against the bundle."""
    rec = refs.json(entry.get("run_record"), f"{lab} run record")
    if rec is None:
        return None
    b = bound.get(entry.get("product"))
    if b is None:
        return None
    bad = []
    if rec.get("test_adapter") is not False or rec.get("product_name") != entry.get("product") or rec.get("adapter_id") != b["adapter"]:
        bad.append("not a real run of this product's adapter")
    if not runner or rec.get("runner_binding") != {**runner, b["adapter_path"]: b["adapter_sha256"]}:
        bad.append("runner files or adapter differ from those bound")
    if rec.get("settings_snapshot_sha256") != b["runtime_settings_snapshot_sha256"]:
        bad.append("runtime settings snapshot differs")
    ident = rec.get("identity") if isinstance(rec.get("identity"), dict) else {}
    if ident.get("executable_sha256") != b["executable_sha256"] or ident.get("version_command") != b["product_version"]:
        bad.append("executable or version differs from the observed identity")
    run = rec.get("run") if isinstance(rec.get("run"), dict) else {}
    if run.get("excluded_from_scoring") is not True or run.get("run_id") != entry.get("run_id", run.get("run_id")):
        bad.append("run id or scoring exclusion")
    st = rec.get("staging") if isinstance(rec.get("staging"), dict) else {}
    if st.get("listing") != WORK_DIR_FILES or rec.get("database_unchanged") is not True or rec.get("task_unchanged") is not True:
        bad.append("staging listing or unchanged files")
    if (rec.get("canary_check") or {}).get("passed") is not True:
        bad.append("canary check")
    t = entry.get("transcript")
    if isinstance(t, dict) and t.get("sha256") != rec.get("transcript_sha256"):
        bad.append("transcript is not the recorded one")
    for f in bad:
        problems.append(f"{lab}: run record: {f}")
    return rec


def _preflight(bundle: dict[str, Any], refs: _Refs, bound: dict[str, dict[str, str]], production_db: str,
               problems: list[str], runner: dict[str, str] | None = None, PRODUCTS: dict[str, Any] = PRODUCTS) -> None:
    pre = bundle.get("preflight") if isinstance(bundle.get("preflight"), dict) else {}
    toys = pre.get("toy_tasks")
    if not isinstance(toys, list) or len(toys) != 2 or {t.get("kind") for t in toys if isinstance(t, dict)} != TOY_KINDS \
            or len({t.get("id") for t in toys if isinstance(t, dict)}) != 2 or not all(_str(t.get("id")) for t in toys):
        problems.append(f"preflight.toy_tasks must be two distinct toy tasks of kinds {sorted(TOY_KINDS)}")
        toys = []
    toy_db = {}
    for t in toys:
        refs.path(t.get("task_md"), f"toy task {t['id']} task.md")
        db = refs.path(t.get("database"), f"toy task {t['id']} database")
        if db is not None:
            toy_db[t["id"]] = _sha(db)
            if toy_db[t["id"]] == production_db:
                problems.append(f"toy task {t['id']}: must not use the production database")
    runs = pre.get("runs")
    expected = {(p, t.get("id"), r) for p in PRODUCTS for t in toys for r in range(1, REPETITIONS + 1)}
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        problems.append("preflight.runs must be a list of run records")
        runs = []
    keys = [(r.get("product"), r.get("toy_task"), r.get("repetition")) for r in runs]
    if len(keys) != 8 or set(keys) != expected or len(set(keys)) != 8:
        problems.append("preflight must hold the eight distinct product x toy task x repetition runs")
    for r in runs:
        lab = f"preflight run {r.get('product')}/{r.get('toy_task')}/{r.get('repetition')}"
        if r.get("excluded_from_scoring") is not True:
            problems.append(f"{lab}: must be excluded from scoring")
        if not _str(r.get("run_id")) or not _str(r.get("outcome_status")) or not _str(r.get("stop_reason")):
            problems.append(f"{lab}: run_id, outcome_status and stop_reason required")
        if not _num(r.get("elapsed_seconds")) or not 0 < r["elapsed_seconds"] <= TIME_LIMIT:
            problems.append(f"{lab}: elapsed_seconds must be within (0, {TIME_LIMIT}]")
        usage = r.get("usage")
        if not isinstance(usage, dict) or not {"input_tokens", "output_tokens", "usage_source"} <= set(usage):
            problems.append(f"{lab}: usage record must carry input_tokens, output_tokens and usage_source (null if unexposed)")
        refs.path(r.get("transcript"), f"{lab} transcript")
        refs.path(r.get("reset_evidence"), f"{lab} reset evidence")
        if r.get("start_listing") != WORK_DIR_FILES:
            problems.append(f"{lab}: start_listing must be exactly {WORK_DIR_FILES}")
        want = toy_db.get(r.get("toy_task"))
        if want is None or r.get("db_sha256_before") != want or r.get("db_sha256_after") != want:
            problems.append(f"{lab}: toy database hash must be unchanged before and after")
        b = bound.get(r.get("product"))
        if b is None or r.get("adapter_sha256") != b["adapter_sha256"] or r.get("settings_snapshot_sha256") != b["settings_snapshot_sha256"]:
            problems.append(f"{lab}: adapter and settings hashes must be those frozen for the product")
        rec = _record(r, refs, bound, runner or {}, lab, problems)
        if rec is not None and b is not None:
            o = rec.get("observed") if isinstance(rec.get("observed"), dict) else {}
            models = set(o.get("models_in_session") or []) | set(o.get("models_in_transcript") or [])
            st = rec.get("staging") or {}
            if b["model"] not in models or not models <= {b["model"], *b["served_aliases"]}:
                problems.append(f"{lab}: run record: observed model {sorted(models)} is not {b['model']}")
            if st.get("database_sha256") != want or rec.get("elapsed_seconds") != r.get("elapsed_seconds") \
                    or rec.get("outcome_status") != r.get("outcome_status") or rec.get("stop_reason") != r.get("stop_reason") \
                    or rec.get("outcome_status") != "completed" or (rec.get("run") or {}).get("repetition") != r.get("repetition"):
                problems.append(f"{lab}: run record: toy database, outcome, stop reason, repetition or elapsed time differ")
    checks = pre.get("adapter_checks")
    checks = checks if isinstance(checks, list) else []
    for name in PRODUCTS:
        for kind in ("forced_timeout", "blocked_access"):
            found = [c for c in checks if isinstance(c, dict) and c.get("product") == name and c.get("check") == kind]
            lab = f"adapter check {name}/{kind}"
            if len(found) != 1:
                problems.append(f"{lab}: exactly one record required")
                continue
            c = found[0]
            refs.path(c.get("evidence"), f"{lab} evidence")
            b = bound.get(name)
            rec = _record(dict(c, product=name), refs, bound, runner or {}, lab, problems)
            if rec is not None:
                left = rec.get("processes_left_after_kill")
                if kind == "forced_timeout" and not (rec.get("stop_reason") == "timeout" and left == 0
                                                     and rec.get("time_limit_s") == c.get("cap_seconds")
                                                     and rec.get("elapsed_seconds") == c.get("stopped_at_seconds")):
                    problems.append(f"{lab}: run record: not a timeout stop at the declared cap with no processes left")
                denied = (rec.get("egress") or {}).get("denied")
                if kind == "blocked_access" and not (isinstance(denied, list) and len(denied) == c.get("denied_requests")):
                    problems.append(f"{lab}: run record: denied requests differ from the declared count")
            if c.get("passed") is not True or b is None or c.get("adapter_sha256") != b["adapter_sha256"] \
                    or c.get("settings_snapshot_sha256") != b["settings_snapshot_sha256"]:
                problems.append(f"{lab}: must pass on the frozen adapter and settings")
            if kind == "forced_timeout" and not (isinstance(c.get("cap_seconds"), int) and c["cap_seconds"] > 0
                                                 and _num(c.get("stopped_at_seconds")) and c["stopped_at_seconds"] <= c["cap_seconds"] + 10
                                                 and c.get("child_processes_remaining") == 0):
                problems.append(f"{lab}: the process tree must be stopped at the cap with no remaining children")
            if kind == "blocked_access" and not (isinstance(c.get("denied_requests"), int) and c["denied_requests"] >= 1
                                                 and c.get("content_obtained") is False):
                problems.append(f"{lab}: access must be denied with no content obtained")


def _dependencies(bundle: dict[str, Any], refs: _Refs, root: Path, build_dir: Path, db_sha: str, problems: list[str],
                  CANONICAL: dict[str, str] = CANONICAL) -> None:
    from generator import tasks
    from generator.certify import check_definitions, check_schemas
    arts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), dict) else {}
    docs = {k: refs.json(arts.get(k), f"artifact {k}", path) for k, path in CANONICAL.items()}
    _fixed(docs["isolation_policy"], ISOLATION_FIXED, "isolation_policy", problems)
    _fixed(docs["failure_policy"], FAILURE_FIXED, "failure_policy", problems)
    for name, (ok, detail) in (("definitions", check_definitions(root)), ("schemas", check_schemas(root))):
        if not ok:
            problems.append(f"{name} not valid: {detail}")
    shas = {k: arts[k]["sha256"] for k in CANONICAL if docs.get(k) is not None}
    exp = docs["task_export_manifest"]
    if exp is not None:
        approval = docs["definitions_approval"] or {}
        if exp.get("tasks") != list(tasks.PILOT_TASKS) or exp.get("database_sha256") != db_sha \
                or exp.get("catalog_sha256") != shas.get("schemas_catalog") \
                or exp.get("definitions_sha256") != approval.get("document_sha256"):
            problems.append("task export manifest is not bound to this database, catalog and approved definitions")
        from .task_package import PACKAGE_VERSION, check_contract, paths
        contract_ok, contract_detail = check_contract(root)
        if not contract_ok:
            problems.append(f"execution contract not approved: {contract_detail}")
        if exp.get("package_version") != PACKAGE_VERSION or exp.get("execution_contract_sha256") != _sha(paths(root)["contract"]):
            problems.append("task export manifest is not package v2 bound to the approved execution contract")
    from .freeze import check_freeze
    ok, detail = check_freeze(root, build_dir)
    if not ok:
        problems.append(f"data freeze does not match: {detail}")
    gold = docs["gold_manifest"]
    if gold is not None:
        bind = {"tasks": list(tasks.PILOT_TASKS), "database_sha256": db_sha, "freeze_sha256": shas.get("data_freeze"),
                "task_export_manifest_sha256": shas.get("task_export_manifest"),
                "catalog_sha256": shas.get("schemas_catalog"),
                "definitions_approval_sha256": shas.get("definitions_approval")}
        for k, v in bind.items():
            if v is None or gold.get(k) != v:
                problems.append(f"gold manifest {k} does not match the certified package")
        entries = gold.get("gold") if isinstance(gold.get("gold"), dict) else {}
        if set(entries) != set(tasks.PILOT_TASKS):
            problems.append("gold manifest must hold one gold file per Pilot-1 task")
        for t in tasks.PILOT_TASKS:
            g = refs.json(entries.get(t), f"gold {t}")
            if g is None:
                continue
            answer = {"schema_version": "1.1", "task_id": t, "status": "answered", "result": g.get("result"),
                      "claims": [], "warnings": [], "assumptions": [], "evidence": []}
            if g.get("task_id") != t or not _schema_ok(root, t, answer):
                problems.append(f"gold {t}: result does not validate against the {t} schema")
    from .policy import check_policy
    pol_ok, pol_detail = check_policy(root, expected_record_sha256=(docs["grader"] or {}).get("policy_record_sha256"))
    if not pol_ok:
        problems.append(f"grading policy does not match the record bound by the grader: {pol_detail}")
    grader = docs["grader"]
    if grader is not None:
        if grader.get("policy_record_sha256") != shas.get("grading_policy"):
            problems.append("grader is not bound to the frozen grading-policy record")
        impl = refs.json(grader.get("code"), "grader implementation manifest", GRADER_IMPLEMENTATION)
        code = root / GRADER_IMPLEMENTATION if impl is not None else None
        if impl is not None:
            from .grader.manifest import MODULES
            mods = impl.get("modules") if isinstance(impl.get("modules"), dict) else {}
            if set(mods) != set(MODULES):
                problems.append("grader implementation manifest must list exactly the scoring modules")
            for m, h in mods.items():
                f = root / m
                if f.is_symlink() or not f.is_file() or _sha(f) != h:
                    problems.append(f"grader implementation file differs: {m}")
            if impl.get("policy_record_sha256") != shas.get("grading_policy") or impl.get("gold_manifest_sha256") != shas.get("gold_manifest") \
                    or (impl.get("rubric") or {}).get("sha256") != (grader.get("rubric") or {}).get("sha256"):
                problems.append("grader implementation manifest is not bound to this policy, gold manifest and rubric")
        rubric = refs.json(grader.get("rubric"), "grader rubric")
        if rubric is not None and (not _str(grader.get("rubric_version")) or rubric.get("rubric_version") != grader.get("rubric_version")
                                   or rubric.get("tasks") != list(tasks.PILOT_TASKS)):
            problems.append("grader rubric: version or task set does not match the grader manifest")
        if gold is None or grader.get("gold_manifest_sha256") != shas.get("gold_manifest"):
            problems.append("grader is not bound to the gold manifest")
        rep = grader.get("replay_tests") if isinstance(grader.get("replay_tests"), dict) else {}
        report = refs.json(rep.get("evidence"), "grader replay report")
        cases = rep.get("cases") if isinstance(rep.get("cases"), dict) else {}
        missing = sorted(REPLAY_CASES - set(cases))
        failing = sorted(k for k, v in cases.items() if v != "passed")
        if missing or failing:
            problems.append(f"grader replay tests: missing {missing}, not passed {failing}")
        if report is not None:
            tested = {"kind": "grader_replay_report",
                      "grader_code_sha256": _sha(code) if code is not None else None,
                      "rubric_sha256": grader["rubric"]["sha256"] if rubric is not None else None,
                      "rubric_version": grader.get("rubric_version"),
                      "gold_manifest_sha256": shas.get("gold_manifest")}
            for k, v in tested.items():
                if v is None or report.get(k) != v:
                    problems.append(f"grader replay report {k} is not the tested grader/rubric/gold version")
            if report.get("cases") != cases:
                problems.append("grader replay report cases differ from the grader manifest")


def _schema_ok(root: Path, task_id: str, answer: dict[str, Any]) -> bool:
    from jsonschema import Draft202012Validator
    schema = json.loads((root / "private" / "tasks" / "schemas" / f"{task_id}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema).is_valid(answer)


def check(root: Path, build_dir: Path, wave: str = "1") -> tuple[bool, Any]:
    from generator import tasks
    from generator.export_duckdb import file_sha256
    root = Path(root).resolve()
    if wave not in WAVES:
        return False, f"unknown wave {wave!r}"
    products, canon = wave_products(wave), canonical(wave)
    path = root / WAVES[wave]["dir"] / "manifest.json"
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "missing"
    if not isinstance(bundle, dict):
        return False, "manifest is not a JSON object"
    problems: list[str] = []
    if bundle.get("contract") != CONTRACT:
        problems.append(f"contract must be {CONTRACT}")
    if bundle.get("wave", "1") != wave:
        problems.append(f"the bundle at {WAVES[wave]['dir']} must declare wave {wave}")
    db_sha = file_sha256(Path(build_dir) / "game.duckdb")
    if bundle.get("database_sha256") != db_sha:
        problems.append("database identity")
    refs = _Refs(root, problems)
    runner, cfg = _runner(bundle, refs, problems)
    bound = _products(bundle, refs, problems, cfg, products)
    _schedule(bundle, tasks.PILOT_TASKS, problems, products)
    _preflight(bundle, refs, bound, db_sha, problems, runner, products)
    _dependencies(bundle, refs, root, Path(build_dir).resolve(), db_sha, problems, canon)
    return not problems, problems or None
