"""Antigravity CLI adapter: `antigravity -p` headless (design 6.3; ID-49), Google-account OAuth from a clean profile.

Antigravity CLI 1.2.16 (Google's official CLI, verified against the release manifest's SHA-512 and Google's Apple team
signature) replaces Gemini CLI, whose personal-account client Google now rejects. Each run gets a fresh HOME/.gemini
holding only the OAuth token, the onboarding/project state and a benchmark settings.json (the run's work directory as the
only trusted workspace; permission deny rules for every URL read, browser action and MCP tool; telemetry and paid
credits off). The model id
`gemini-3.8-flash-high` carries the High reasoning level.

The CLI talks to its own local language server on 127.0.0.1, so this adapter declares SANDBOX_EXTRA: localhost bind,
inbound and outbound. That is wider than the other products' boundary (they reach only the egress proxy); it is recorded
in every run record and disclosed. Other local services must not run during the wave.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ._common import jsonl, resolve, version_and_hash, walk

ADAPTER_ID = "antigravity_cli"
SANDBOX_EXTRA = """(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(allow file-read-data file-write* (literal "/dev/ptmx"))
"""
STATE_FILES = ("antigravity-cli/antigravity-oauth-token", "antigravity-cli/cache/onboarding.json",
               "antigravity-cli/cache/default_project_id.txt", "config/projects/default-cli-project.json")


def _settings(spec: dict[str, Any], work: Path) -> dict[str, Any]:
    """Documented keys (antigravity.google/docs/cli/reference and /docs/permissions, 2026-10-04). The deny list blocks every
    URL read, browser action and MCP tool; terminal commands and workspace file tools proceed without prompts."""
    return {"trustedWorkspaces": [str(work)], "toolPermission": "always-proceed", "enableTelemetry": False, "useG1Credits": False,
            "allowNonWorkspaceAccess": False, "showFeedbackSurvey": False,
            "permissions": {"deny": list(spec["permission_deny"]), "allow": ["command(*)"]}}


def prepare(spec: dict[str, Any], home: Path, root: Path) -> tuple[list[Path], dict[str, str]]:
    baseline = resolve(spec["profile_baseline"], root) / ".gemini"
    if not (baseline / STATE_FILES[0]).is_file():
        raise RuntimeError(f"Antigravity baseline profile is not logged in ({baseline}); run the owner login step first")
    g = home / ".gemini"
    for rel in STATE_FILES:
        src = baseline / rel
        if src.is_file():
            (g / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, g / rel)                      # credentials copied by the runner, never displayed
            (g / rel).chmod(0o600)
    (g / "config" / "mcp_config.json").write_text("{}\n", encoding="utf-8")
    work = home.parent / "work"
    (g / "antigravity-cli" / "settings.json").write_text(json.dumps(_settings(spec, work), indent=1), encoding="utf-8")
    return [resolve(spec["install_root"], root)], {}


def argv(spec: dict[str, Any], work: Path, prompt: str) -> list[str]:
    root = Path(__file__).resolve().parents[3]
    return [str(resolve(spec["binary"], root)), "-p", prompt, "--output-format", "stream-json", "--model", spec["model"]]


def identity(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    return {**version_and_hash(resolve(spec["binary"], root)), "model_requested": spec["model"], "reasoning_setting": spec["reasoning_effort"],
            "model_provider": "Google", "model_selection_source": "explicit"}


def settings_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    keep = ("adapter", "model", "reasoning_effort", "disallowed_tools", "permission_deny", "egress_allowlist", "benchmark_overrides",
            "expected_version")
    return {k: spec[k] for k in keep} | {"flags": ["-p", "--output-format stream-json"],
                                           "settings_json": _settings(spec, Path("<run>/work")), "sandbox_extra": SANDBOX_EXTRA}


def collect(home: Path, out_dir: Path) -> dict[str, Any]:
    """Copy the CLI's own log from the disposable home (model and tool evidence); conversation stores are not copied."""
    import hashlib
    logs = sorted((home / ".gemini" / "antigravity-cli" / "log").glob("*.log")) if (home / ".gemini" / "antigravity-cli" / "log").exists() else []
    out = {}
    for i, f in enumerate(logs[:10]):
        dest = out_dir / f"session_{i}.log"
        shutil.copyfile(f, dest)
        out[dest.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    return {"session_files": out}


def parse(stdout: Path, stderr: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    events = jsonl(stdout)
    models, usage, tools, names = set(), None, 0, set()
    for ev in events:
        for d in walk(ev):
            for k in ("model", "modelId", "model_id"):
                if isinstance(d.get(k), str) and ("gemini" in d[k] or "flash" in d[k]):
                    models.add(d[k])
            if isinstance(d.get("usage"), dict):
                usage = d["usage"]
            if d.get("type") in ("tool_use", "tool_call") or "tool_name" in d or "toolName" in d:
                tools += 1
                n = d.get("name") or d.get("tool_name") or d.get("toolName")
                if isinstance(n, str):
                    names.add(n)
    u = ({**{k: usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "total_tokens") if k in usage},
          "usage_source": "antigravity stream-json usage"} if usage else
         {"input_tokens": None, "output_tokens": None, "usage_source": None, "reason": "no usage in the stream"})
    web = sorted(n for n in names if any(w in n.lower() for w in ("search", "url", "browser", "web")))
    searches = []                                           # ID-53: search_web cannot be disabled; every query is recorded
    for ev in events:
        su = ev.get("step_update") or {}
        if su.get("tool_name") == "search_web" and su.get("state") in ("DONE", "ERROR"):
            q = ((su.get("tool_info") or {}).get("parameters") or {}).get("query")
            searches.append({"query": q, "state": su.get("state")})
    return u, {"models_in_transcript": sorted(models), "events": len(events), "tool_events": tools, "tool_names": sorted(names),
               "web_tool_uses": web, "web_searches": searches, "web_search_count": len(searches), "quota": None}
