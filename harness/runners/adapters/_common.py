"""Shared adapter helpers (identity observation and generic JSONL usage parsing)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def resolve(p: str, root: Path) -> Path:
    q = Path(p)
    return (q if q.is_absolute() else root / q).resolve()


def version_and_hash(binary: Path) -> dict[str, Any]:
    r = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=60)
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and "PATH aliases" not in l]
    return {"version_command": lines[-1].strip() if lines else None, "executable": str(binary),
            "executable_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}


def jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)
