"""Stage 1: preserve and validate a submission (no code is executed here).

A submission directory holds answer.json, memo.md and any evidence files. Before anything is parsed, every regular file
is copied into an immutable archive with its SHA-256 (symlinks and special files are recorded, never followed). Then:
  - answer.json is parsed STRICTLY: duplicate object keys and NaN/Infinity constants are rejected; the parsed value is
    validated against the frozen task schema (Draft 2020-12; booleans are not numbers);
  - evidence and transformation paths must be relative regular files inside the submission (replay.safe_member rules);
    an evidence reference to a provided input (task.md, game.duckdb: present in the analyst's directory but not part of
    the submission) is valid and recorded in provided_input_refs (ID-48); a transformation must be submitted code;
  - memo.md is read as UTF-8 and its word count recorded (the contract asks for 150-400 words).
Format status is kept separate from substance: a malformed answer with a memo still goes to claim review, and empty
output, a pure refusal and a substantive not_identifiable answer remain distinguishable.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass, field

PROVIDED_INPUTS = ("task.md", "game.duckdb")      # the staged inputs: valid evidence references, never archived (ID-48)
from pathlib import Path
from typing import Any

MAX_ANSWER_BYTES = 2 * 1024 ** 2
MAX_MEMO_BYTES = 1024 ** 2


class StrictJSONError(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise StrictJSONError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _no_constants(name: str) -> Any:
    raise StrictJSONError(f"non-finite constant {name}")


def _finite_float(token: str) -> float:
    import math
    v = float(token)
    if not math.isfinite(v):
        raise StrictJSONError(f"number {token[:40]!r} is not representable as a finite double")
    return v


def strict_loads(text: str) -> Any:
    """Duplicate keys, NaN/Infinity constants and numbers that overflow a double (e.g. 1e309) are rejected."""
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants, parse_float=_finite_float)


@dataclass
class Intake:
    run_id: str
    task_id: str
    archive: dict[str, dict[str, Any]] = field(default_factory=dict)   # relpath -> {sha256, bytes} or {special: kind}
    answer_present: bool = False
    answer_parse: str = "missing"              # ok | missing | too_large | not_utf8 | invalid_json | invalid_number | schema_invalid
    answer_errors: list[str] = field(default_factory=list)
    answer: Any = None                          # parsed value when the JSON itself parsed (even if schema-invalid)
    status: str | None = None                   # answered | partial | not_identifiable (when readable)
    memo_present: bool = False
    memo: str = ""
    memo_words: int = 0
    evidence_errors: list[str] = field(default_factory=list)
    provided_input_refs: list[str] = field(default_factory=list)
    transformation: str | None = None

    @property
    def format_ok(self) -> bool:
        return self.answer_parse == "ok" and self.memo_present and not self.evidence_errors

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["format_ok"] = self.format_ok
        return d


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def preserve(submission: Path, archive_dir: Path) -> dict[str, dict[str, Any]]:
    """Copy every regular file (no links followed) into archive_dir and return the inventory with hashes."""
    inv: dict[str, dict[str, Any]] = {}
    submission = Path(submission)
    for dirpath, dirnames, filenames in os.walk(submission, followlinks=False):
        for name in sorted(filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]):
            p = Path(dirpath) / name
            rel = p.relative_to(submission).as_posix()
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                inv[rel] = {"special": "symlink" if stat.S_ISLNK(st.st_mode) else "other"}
                continue
            dest = Path(archive_dir) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest, follow_symlinks=False)
            dest.chmod(0o444)
            inv[rel] = {"sha256": _sha(dest), "bytes": st.st_size}
    return inv


def intake(run_id: str, task_id: str, submission: Path, archive_dir: Path, schema: dict[str, Any]) -> Intake:
    from jsonschema import Draft202012Validator
    from evaluation.replay import ReplayRejected, safe_member
    res = Intake(run_id, task_id)
    res.archive = preserve(submission, archive_dir)
    base = Path(archive_dir)                     # everything below reads the preserved copy, never the live directory
    ans = base / "answer.json"
    if "answer.json" in res.archive and "sha256" in res.archive["answer.json"]:
        res.answer_present = True
        raw = ans.read_bytes()
        if len(raw) > MAX_ANSWER_BYTES:
            res.answer_parse = "too_large"
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                res.answer_parse = "not_utf8"
            else:
                try:
                    res.answer = strict_loads(text)
                except (ValueError, RecursionError) as exc:
                    kind = "invalid_number" if "finite double" in str(exc) else "invalid_json"
                    res.answer_parse, res.answer_errors = kind, [str(exc)[:300]]
                else:
                    errs = sorted(e.message[:300] for e in Draft202012Validator(schema).iter_errors(res.answer))
                    if isinstance(res.answer, dict) and res.answer.get("task_id") != task_id:
                        errs.append(f"task_id must be {task_id}")
                    res.answer_parse, res.answer_errors = ("schema_invalid", errs) if errs else ("ok", [])
                    if isinstance(res.answer, dict) and res.answer.get("status") in ("answered", "partial", "not_identifiable"):
                        res.status = res.answer["status"]
    memo = base / "memo.md"
    if "memo.md" in res.archive and "sha256" in res.archive["memo.md"]:
        raw = memo.read_bytes()[:MAX_MEMO_BYTES]
        res.memo_present = True
        res.memo = raw.decode("utf-8", "replace")
        res.memo_words = len(res.memo.split())
    if isinstance(res.answer, dict):            # path safety is checked whenever the JSON parsed, schema-valid or not
        ev = res.answer.get("evidence") if isinstance(res.answer.get("evidence"), list) else []
        refs = [e.get("path") for e in ev if isinstance(e, dict) and isinstance(e.get("path"), str)]
        result = res.answer.get("result")
        if isinstance(result, dict) and isinstance(result.get("transformation_path"), str):
            res.transformation = result["transformation_path"]
            refs.append(res.transformation)
        for r in refs:
            if os.path.normpath(r) in PROVIDED_INPUTS and r != res.transformation:
                res.provided_input_refs.append(r)
                continue
            try:
                safe_member(base, r)
            except ReplayRejected as exc:
                res.evidence_errors.append(f"{r}: {exc}")
    return res
