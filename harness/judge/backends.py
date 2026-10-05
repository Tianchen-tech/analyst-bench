"""Judge-panel backends (ID-50): one judgment = one fresh headless CLI call with the judge-v1 prompt.

  gpt     Codex CLI `codex exec` (gpt-6.1-sol, effort high), read-only sandbox, ephemeral, web search off; the prompt on
          stdin; the final message (-o) is parsed. ChatGPT subscription via a throwaway CODEX_HOME holding only auth.json.
  claude  Claude Code `claude -p` (claude-opus-5-5, effort high), no tools (--tools ""), no settings sources, no MCP, no
          session persistence, structured output (--json-schema); the prompt on stdin. Claude subscription token.
  grok    Grok Build CLI (grok-4.7, effort high), web search and subagents off, structured output; a throwaway GROK_HOME
          holding only auth.json and the bundled resources (never the owner's ~/.grok).
Every call runs in a new empty working directory with a minimal environment (no API keys). The judges see only the
blind prompt; which judges judge a packet (leave-own-provider-out) is decided by the panel runner, not here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import judge as J

ROOT = Path(__file__).resolve().parents[2]
JUDGES = {"gpt": "OpenAI", "claude": "Anthropic", "grok": "xAI"}
PROVIDER = {"Codex": "OpenAI", "Claude Code": "Anthropic", "Grok Build": "xAI", "Antigravity": "Google"}
MODELS = {"gpt": ("gpt-6.1-sol", "high"), "claude": ("claude-opus-5-5", "high"), "grok": ("grok-4.7", "high")}
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
CLAUDE = ROOT / ".tools/claude-code/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
GROK = ROOT / ".tools/grok-build/bin/grok"
TIMEOUT = 1800


def _env(home: Path, **extra: str) -> dict[str, str]:
    return {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(home), "LANG": "en_US.UTF-8", **extra}


def _run(argv: list[str], cwd: Path, env: dict[str, str], stdin: str | None) -> tuple[Any, str, str]:
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as exc:
        dec = lambda b: b.decode() if isinstance(b, bytes) else (b or "")
        return "timeout", dec(exc.stdout), dec(exc.stderr)


def call(judge: str, prompt: str, out_dir: Path, tag: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{tag}.prompt.md").write_text(prompt, encoding="utf-8")
    model, effort = MODELS[judge]
    with tempfile.TemporaryDirectory(prefix="judge-") as t:
        t = Path(t)
        home, wd = t / "home", t / "work"
        home.mkdir(), wd.mkdir()
        if judge == "gpt":
            ch = home / ".codex"
            ch.mkdir()
            shutil.copyfile(ROOT / ".tools/profiles/codex/auth.json", ch / "auth.json")
            (ch / "auth.json").chmod(0o600)
            last = t / "last.txt"
            argv = [CODEX, "exec", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "--ephemeral", "-m", model,
                    "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"', "-s", "read-only", "-C", str(wd),
                    "-o", str(last), "-"]
            rc, so, se = _run(argv, wd, _env(home, CODEX_HOME=str(ch)), prompt)
            final = last.read_text(encoding="utf-8") if last.exists() else ""
            parsed = J.extract_json(final)
            meta = {"models": [model], "final_message_chars": len(final)}
            so = so + "\n<<FINAL MESSAGE>>\n" + final
        elif judge == "claude":
            token = (ROOT / ".tools/profiles/claude/oauth_token").read_text(encoding="utf-8").strip()    # never printed
            cfg = home / ".claude"
            cfg.mkdir()
            argv = [str(CLAUDE), "-p", "--output-format", "json", "--model", model, "--effort", effort, "--tools", "",
                    "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence", "--json-schema", json.dumps(J.SCHEMA)]
            rc, so, se = _run(argv, wd, _env(home, CLAUDE_CONFIG_DIR=str(cfg), CLAUDE_CODE_OAUTH_TOKEN=token, DISABLE_TELEMETRY="1",
                                             DISABLE_ERROR_REPORTING="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                                             DISABLE_AUTOUPDATER="1"), prompt)
            parsed = J.extract_json(so)
            meta = {}
            try:
                top = json.loads(so)
                meta = {"models": sorted((top.get("modelUsage") or {}).keys()), "num_turns": top.get("num_turns"),
                        "usage": top.get("usage"), "is_error": top.get("is_error")}
            except (ValueError, AttributeError):
                pass
        elif judge == "grok":
            gh = home / ".grok"
            gh.mkdir()
            shutil.copyfile(ROOT / ".tools/profiles/grok/auth.json", gh / "auth.json")
            (gh / "auth.json").chmod(0o600)
            for d in ("bundled", "vendor"):
                shutil.copytree(ROOT / ".tools/grok-build" / d, gh / d, symlinks=True)
            pf = t / "prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            argv = J.grok_argv(str(GROK), pf, wd, model, effort) + ["--no-auto-update"]
            rc, so, se = _run(argv, wd, _env(home, GROK_HOME=str(gh)), None)
            parsed = J.extract_json(so)
            meta = {}
            try:
                top = json.loads(so)
                meta = {"models": sorted((top.get("modelUsage") or {}).keys()), "num_turns": top.get("num_turns"), "usage": top.get("usage")}
            except (ValueError, AttributeError):
                pass
        else:
            raise ValueError(judge)
    (out_dir / f"{tag}.stdout").write_text(so, encoding="utf-8")
    (out_dir / f"{tag}.stderr").write_text(se, encoding="utf-8")
    return {"tag": tag, "judge": judge, "returncode": rc, "prompt_sha256": J.sha(prompt), "stdout_sha256": J.sha(so),
            "parsed": parsed, "meta": meta}
