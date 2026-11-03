"""Product adapters: identity comes from the settings and the binary, observations from the transcript."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from runners.adapters import claude_code_print as claude
from runners.adapters import codex_exec as codex


def write_jsonl(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + "not json\n", encoding="utf-8")
    return path


def test_claude_transcript_parsing(tmp_path: Path):
    stdout = write_jsonl(tmp_path / "transcript.jsonl", [
        {"type": "system", "subtype": "init", "model": "test-model", "tools": ["Read", "Bash"],
         "permissionMode": "acceptEdits", "claude_code_version": "2.1.289", "per_turn_effort_active": True},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "overageStatus": "rejected", "isUsingOverage": False,
                                                         "unifiedWindows": {"five_hour": {"utilization": 0.4}, "seven_day": {"utilization": 0.2}}}},
        {"type": "result", "is_error": False, "modelUsage": {"test-model": {}}, "total_cost_usd": 0.12,
         "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3}},
    ])
    usage, observed = claude.parse(stdout, tmp_path / "stderr.log")
    assert (usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]) == (10, 3, 5)
    assert observed["models_in_transcript"] == ["test-model"]
    assert observed["tool_uses"] == 1 and observed["web_tool_uses"] == 0
    assert observed["quota"]["five_hour_utilization"] == 0.4
    assert observed["per_turn_effort_active"] is True
    assert "effort_requested" not in observed                     # the transcript does not show the requested level
    assert "identity.reasoning_setting" in observed["effort_note"]


@pytest.mark.skipif(os.name != "posix", reason="executable shell script")
def test_requested_effort_is_recorded_from_the_settings(tmp_path: Path):
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\necho '2.1.289 (Claude Code)'\n", encoding="utf-8")
    binary.chmod(0o755)
    spec = {"binary": str(binary), "model": "test-model", "reasoning_effort": "max"}
    ident = claude.identity(spec, tmp_path)
    assert ident["reasoning_setting"] == "max" and ident["model_requested"] == "test-model"
    assert ident["version_command"] == "2.1.289 (Claude Code)"
    assert ident["executable_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()


def test_codex_usage_is_summed_over_turns(tmp_path: Path):
    stdout = write_jsonl(tmp_path / "transcript.jsonl", [
        {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 7}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
        {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 3, "reasoning_output_tokens": 2}},
    ])
    usage, observed = codex.parse(stdout, tmp_path / "stderr.log")
    assert (usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"], usage["reasoning_tokens"]) == (150, 40, 10, 2)
    assert observed["tool_events"] == 1 and observed["web_search_events"] == 0
