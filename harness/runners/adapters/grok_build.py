"""Grok Build adapter: `grok -p` headless (design 6.3; ID-49), grok.com-subscription authentication from a clean GROK_HOME.

The binary and its bundled agents/vendor tools are a project copy (.tools/grok-build), so the contestant never reads the
owner's ~/.grok (which holds the wave-1 judge sessions). Each run gets a fresh GROK_HOME inside the run's home with only
the credential file and the bundled resources; sessions it writes there are copied out as evidence.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ._common import jsonl, resolve, version_and_hash, walk

ADAPTER_ID = "grok_build"


def prepare(spec: dict[str, Any], home: Path, root: Path) -> tuple[list[Path], dict[str, str]]:
    baseline = resolve(spec["profile_baseline"], root)
    auth = baseline / "auth.json"
    if not auth.is_file():
        raise RuntimeError(f"Grok baseline profile is not logged in ({baseline}); run the owner login step first")
    install = resolve(spec["install_root"], root)
    grok_home = home / ".grok"
    grok_home.mkdir()
    shutil.copyfile(auth, grok_home / "auth.json")             # credentials copied by the runner, never displayed
    (grok_home / "auth.json").chmod(0o600)
    for d in ("bundled", "vendor"):
        shutil.copytree(install / d, grok_home / d, symlinks=True)
    return [install], {"GROK_HOME": str(grok_home)}


def argv(spec: dict[str, Any], work: Path, prompt: str) -> list[str]:
    root = Path(__file__).resolve().parents[3]
    return [str(resolve(spec["binary"], root)), "-p", prompt, "--output-format", "streaming-json", "-m", spec["model"],
            "--reasoning-effort", spec["reasoning_effort"], "--always-approve", "--disable-web-search",
            "--disallowed-tools", ",".join(spec["disallowed_tools"]), "--cwd", str(work), "--no-auto-update"]


def identity(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    return {**version_and_hash(resolve(spec["binary"], root)), "model_requested": spec["model"], "reasoning_setting": spec["reasoning_effort"],
            "model_provider": "xAI", "model_selection_source": "explicit"}


def settings_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    keep = ("adapter", "model", "reasoning_effort", "disallowed_tools", "egress_allowlist", "benchmark_overrides", "expected_version")
    return {k: spec[k] for k in keep} | {"flags": ["-p", "--output-format streaming-json", "--always-approve", "--disable-web-search",
                                                    "--no-auto-update", "fresh GROK_HOME (auth + bundled + vendor only)"]}


def collect(home: Path, out_dir: Path) -> dict[str, Any]:
    """Copy the session files Grok wrote in the disposable GROK_HOME: the controller's evidence of model and effort."""
    import hashlib
    files = sorted(p for p in (home / ".grok" / "sessions").rglob("*") if p.is_file()) if (home / ".grok" / "sessions").exists() else []
    out = {}
    for i, f in enumerate(files[:50]):
        dest = out_dir / f"session_{i}{f.suffix or '.dat'}"
        shutil.copyfile(f, dest)
        out[dest.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    return {"session_files": out}


def parse(stdout: Path, stderr: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    events = jsonl(stdout)
    models, efforts, usage, cost, tools = set(), set(), None, None, 0
    for ev in events:
        for d in walk(ev):
            if isinstance(d.get("modelUsage"), dict):
                models |= set(d["modelUsage"])
            for k in ("model", "modelId", "model_id"):
                if isinstance(d.get(k), str) and d[k].startswith("grok"):
                    models.add(d[k])
            for k in ("reasoningEffort", "reasoning_effort", "effort"):
                if isinstance(d.get(k), str):
                    efforts.add(d[k])
            if isinstance(d.get("usage"), dict) and "input_tokens" in d["usage"]:
                usage = d["usage"]
            if isinstance(d.get("total_cost_usd"), (int, float)):
                cost = d["total_cost_usd"]
            if d.get("sessionUpdate") in ("tool_call", "tool_call_update") or d.get("type") == "tool_use":
                tools += 1
    for f in sorted(Path(stdout).parent.glob("session_*")):
        for ev in jsonl(f):
            for d in walk(ev):
                for k in ("model", "modelId"):
                    if isinstance(d.get(k), str) and d[k].startswith("grok"):
                        models.add(d[k])
    u = ({"input_tokens": usage.get("input_tokens"), "cached_input_tokens": usage.get("cache_read_input_tokens"),
          "output_tokens": usage.get("output_tokens"), "reasoning_tokens": usage.get("reasoning_tokens"),
          "usage_source": "grok streaming-json usage", "reported_cost_usd": cost,
          "reported_cost_usd_label": "CLI-reported figure; under a grok.com subscription login this is not a separate charge"}
         if usage else {"input_tokens": None, "output_tokens": None, "usage_source": None, "reason": "no usage in the stream"})
    return u, {"models_in_transcript": sorted(models), "efforts_in_transcript": sorted(efforts), "events": len(events), "tool_events": tools,
               "quota": None}
