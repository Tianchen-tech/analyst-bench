"""Codex adapter: `codex exec` headless (design 6.3), ChatGPT-subscription authentication from a clean baseline profile."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ._common import jsonl, resolve, version_and_hash, walk

ADAPTER_ID = "codex_exec"


def prepare(spec: dict[str, Any], home: Path, root: Path) -> tuple[list[Path], dict[str, str]]:
    baseline = resolve(spec["profile_baseline"], root)
    auth = baseline / "auth.json"
    if not auth.is_file():
        raise RuntimeError(f"Codex baseline profile is not logged in ({baseline}); run the owner login step first")
    codex_home = home / ".codex"
    codex_home.mkdir()
    shutil.copyfile(auth, codex_home / "auth.json")            # credentials copied by the runner, never displayed
    (codex_home / "auth.json").chmod(0o600)
    return [resolve(spec["install_root"], root)], {"CODEX_HOME": str(codex_home)}


def argv(spec: dict[str, Any], work: Path, prompt: str) -> list[str]:
    return [str(resolve(spec["binary"], Path("/"))), "exec", "--json", "--skip-git-repo-check", "--ignore-user-config",
            "--ignore-rules", "-m", spec["model"], "-c", f'model_reasoning_effort="{spec["reasoning_effort"]}"',
            "-c", 'web_search="disabled"', "--dangerously-bypass-approvals-and-sandbox", "-C", str(work), prompt]


def identity(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    return {**version_and_hash(resolve(spec["binary"], root)), "model_requested": spec["model"], "reasoning_setting": spec["reasoning_effort"],
            "model_provider": "OpenAI", "model_selection_source": "explicit"}


def settings_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    keep = ("adapter", "model", "reasoning_effort", "egress_allowlist", "benchmark_overrides", "expected_version")
    return {k: spec[k] for k in keep} | {"flags": ["--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                                                    "web_search=disabled", "--dangerously-bypass-approvals-and-sandbox"]}


def collect(home: Path, out_dir: Path) -> dict[str, Any]:
    """Copy Codex's session rollout(s) from the disposable per-run home: the controller's evidence of model and effort."""
    import hashlib
    files = sorted((home / ".codex" / "sessions").rglob("*.jsonl")) if (home / ".codex" / "sessions").exists() else []
    out = {}
    for i, f in enumerate(files):
        dest = out_dir / f"session_rollout_{i}.jsonl"
        shutil.copyfile(f, dest)
        out[dest.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    return {"rollouts": out}


def _session_identity(out_dir: Path) -> dict[str, Any]:
    models, efforts, quota = set(), set(), None
    for f in sorted(out_dir.glob("session_rollout_*.jsonl")):
        for ev in jsonl(f):
            for d in walk(ev):
                if isinstance(d.get("model"), str):
                    models.add(d["model"])
                for k in ("effort", "reasoning_effort", "model_reasoning_effort"):
                    if isinstance(d.get(k), str):
                        efforts.add(d[k])
                rl = d.get("rate_limits")
                if isinstance(rl, dict) and isinstance(rl.get("primary"), dict):
                    quota = {"five_hour_used_percent": rl["primary"].get("used_percent"), "five_hour_resets_at": rl["primary"].get("resets_at"),
                             "weekly_used_percent": (rl.get("secondary") or {}).get("used_percent"),
                             "weekly_resets_at": (rl.get("secondary") or {}).get("resets_at")}
    return {"models_in_session": sorted(models), "efforts_in_session": sorted(efforts), "quota": quota}


def parse(stdout: Path, stderr: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    events = jsonl(stdout)
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    seen = False
    models = set()
    for ev in events:
        for d in walk(ev):
            u = d.get("usage")
            if isinstance(u, dict) and ev.get("type") in ("turn.completed", "token_count", "turn.complete"):
                seen = True
                usage["input_tokens"] += int(u.get("input_tokens") or 0)
                usage["cached_input_tokens"] += int(u.get("cached_input_tokens") or 0)
                usage["output_tokens"] += int(u.get("output_tokens") or 0)
                usage["reasoning_tokens"] += int(u.get("reasoning_output_tokens") or u.get("reasoning_tokens") or 0)
            if isinstance(d.get("model"), str):
                models.add(d["model"])
    tools = sum(1 for ev in events for d in walk(ev) if d.get("type") in ("command_execution", "web_search", "mcp_tool_call"))
    web = sum(1 for ev in events for d in walk(ev) if d.get("type") == "web_search")
    return ({**usage, "usage_source": "codex exec --json events"} if seen else
            {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
             "usage_source": None, "reason": "no usage events in the transcript"}), \
        {"models_in_transcript": sorted(models), "events": len(events), "tool_events": tools, "web_search_events": web,
         **_session_identity(Path(stdout).parent)}
