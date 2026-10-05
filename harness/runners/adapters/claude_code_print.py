"""Claude Code adapter: `claude -p` headless (design 6.3), Claude-subscription authentication via a setup-token file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import jsonl, resolve, version_and_hash, walk

ADAPTER_ID = "claude_code_print"


def prepare(spec: dict[str, Any], home: Path, root: Path) -> tuple[list[Path], dict[str, str]]:
    token_file = resolve(spec["profile_baseline"], root) / "oauth_token"
    if not token_file.is_file():
        raise RuntimeError(f"Claude subscription token file missing ({token_file}); the owner creates it with `claude setup-token`")
    token = token_file.read_text(encoding="utf-8").strip()           # never printed or recorded
    cfg_dir = home / ".claude"
    cfg_dir.mkdir()
    return [resolve(spec["install_root"], root)], {
        "CLAUDE_CONFIG_DIR": str(cfg_dir), "CLAUDE_CODE_OAUTH_TOKEN": token, "CLAUDE_CODE_TMPDIR": str(home.parent / "tmp"), "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"}


def argv(spec: dict[str, Any], work: Path, prompt: str) -> list[str]:
    root = Path(__file__).resolve().parents[3]
    return [str(resolve(spec["binary"], root)), "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--model", spec["model"], "--effort", spec["reasoning_effort"], "--permission-mode", "acceptEdits",
            "--allowedTools", ",".join(spec["frozen_tool_allowlist"]), "--disallowedTools", ",".join(spec["disallowed_tools"]),
            "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence"]


def identity(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    return {**version_and_hash(resolve(spec["binary"], root)), "model_requested": spec["model"], "reasoning_setting": spec["reasoning_effort"],
            "model_provider": "Anthropic", "model_selection_source": "explicit"}


def settings_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    keep = ("adapter", "model", "reasoning_effort", "frozen_tool_allowlist", "disallowed_tools", "egress_allowlist", "benchmark_overrides",
            "expected_version")
    return {k: spec[k] for k in keep} | {"flags": ["-p", "--output-format stream-json", "--permission-mode acceptEdits", "--setting-sources ''",
                                                    "--strict-mcp-config", "--no-session-persistence"]}


def parse(stdout: Path, stderr: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    events = jsonl(stdout)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    models = set(init.get("model") and [init["model"]] or [])
    if result and isinstance(result.get("modelUsage"), dict):
        models |= set(result["modelUsage"])
    tools = [d.get("name") for e in events for d in walk(e) if d.get("type") == "tool_use"]
    if result and isinstance(result.get("usage"), dict):
        u = result["usage"]
        usage = {"input_tokens": u.get("input_tokens"), "cached_input_tokens": (u.get("cache_read_input_tokens") or 0),
                 "cache_creation_input_tokens": u.get("cache_creation_input_tokens"), "output_tokens": u.get("output_tokens"),
                 "reasoning_tokens": None, "usage_source": "claude -p stream-json result event",
                 "reported_cost_usd_label": "product-reported API-equivalent estimate, not a subscription charge",
                 "reported_cost_usd": result.get("total_cost_usd")}
    else:
        usage = {"input_tokens": None, "output_tokens": None, "usage_source": None, "reason": "no result event"}
    rl = [e.get("rate_limit_info") for e in events if e.get("type") == "rate_limit_event" and isinstance(e.get("rate_limit_info"), dict)]
    quota = None
    if rl:
        last = rl[-1]
        win = last.get("unifiedWindows") or {}
        quota = {"status": last.get("status"), "five_hour_utilization": (win.get("five_hour") or {}).get("utilization"),
                 "seven_day_utilization": (win.get("seven_day") or {}).get("utilization"), "resets_at": last.get("resetsAt"),
                 "overage": last.get("overageStatus"), "using_overage": last.get("isUsingOverage")}
    return usage, {"models_in_transcript": sorted(m for m in models if m), "events": len(events), "tool_uses": len(tools),
                   "effort_requested": "high", "per_turn_effort_active": init.get("per_turn_effort_active"),
                   "effort_level_observed": None, "effort_note": "the product does not echo the effort level; the flag was passed",
                   "tools_available": init.get("tools"), "permission_mode": init.get("permissionMode"),
                   "claude_code_version": init.get("claude_code_version"), "quota": quota,
                   "web_tool_uses": sum(1 for t in tools if t in ("WebSearch", "WebFetch")),
                   "permission_denials": (result or {}).get("permission_denials"), "is_error": (result or {}).get("is_error")}
