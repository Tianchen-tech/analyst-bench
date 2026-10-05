"""Scorer implementation manifest and entry gate.

private/grading/implementation.json binds, by SHA-256, every local module that affects scoring (all grader modules, the
helpers they import: aliases, scoring, replay, policy, freeze, gold and reference (gold replay at the gate), and the
scripts/grade.py entry point) plus the rubric, the gold manifest and the
grading-policy record. The entry gate (`gate`) runs before any submission is loaded and raises GateError, an
infrastructure outcome that stops scoring, when anything differs: the data/task freeze, the gold manifest binding, the
policy record hash and contents, the live runtime check, or any implementation file. Nothing is re-attested or
re-frozen automatically. Every score artifact records the identities returned by `gate`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

IMPLEMENTATION = "private/grading/implementation.json"
RUBRIC = "private/grading/rubric.json"
MODULES = ("private/evaluation/grader/__init__.py", "private/evaluation/grader/intake.py", "private/evaluation/grader/atoms.py",
           "private/evaluation/grader/tasks.py", "private/evaluation/grader/score.py", "private/evaluation/grader/review.py",
           "private/evaluation/grader/aggregate.py", "private/evaluation/grader/manifest.py", "private/evaluation/aliases.py",
           "private/evaluation/scoring.py", "private/evaluation/replay.py", "private/evaluation/policy.py", "private/evaluation/freeze.py",
           "private/evaluation/gold.py", "private/evaluation/reference.py", "scripts/grade.py",
           "private/judge/judge.py", "private/judge/backends.py", "scripts/panel_combine.py", "scripts/final_results.py",
           "scripts/regrade_pilot1.py")


class GateError(RuntimeError):
    """Scoring must not start (infrastructure, not a contestant error)."""


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_implementation(root: Path) -> dict[str, Any]:
    from evaluation.policy import record_sha256
    root = Path(root).resolve()
    gm = root / "private" / "gold" / "manifest.json"
    doc = {"kind": "scorer_implementation", "rules": "scorer-v1", "modules": {m: _sha(root / m) for m in MODULES},
           "rubric": {"path": RUBRIC, "sha256": _sha(root / RUBRIC)},
           "rubric_version": json.loads((root / RUBRIC).read_text())["rubric_version"],
           "gold_manifest_sha256": _sha(gm), "policy_record_sha256": record_sha256(root)}
    (root / IMPLEMENTATION).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def gate(root: Path, build_dir: Path) -> dict[str, Any]:
    from evaluation.freeze import check_freeze, record_sha256 as freeze_sha
    from evaluation.gold import check_gold
    from evaluation.policy import check_policy
    root = Path(root).resolve()
    impl_path = root / IMPLEMENTATION
    if not impl_path.is_file():
        raise GateError("scorer implementation manifest missing")
    impl = json.loads(impl_path.read_text(encoding="utf-8"))
    problems = []
    if set(impl.get("modules", {})) != set(MODULES):
        problems.append("implementation manifest does not list exactly the scoring modules")
    for m in MODULES:
        p = root / m
        if not p.is_file() or p.is_symlink() or _sha(p) != impl.get("modules", {}).get(m):
            problems.append(f"implementation file changed: {m}")
    if _sha(root / RUBRIC) != (impl.get("rubric") or {}).get("sha256"):
        problems.append("rubric changed")
    ok, detail = check_freeze(root, build_dir)
    if not ok:
        problems.append(f"data/task freeze: {detail}")
    gm = root / "private" / "gold" / "manifest.json"
    gold_manifest = json.loads(gm.read_text(encoding="utf-8"))
    if _sha(gm) != impl.get("gold_manifest_sha256") or gold_manifest.get("freeze_sha256") != freeze_sha(root):
        problems.append("gold manifest is not the bound one or not bound to the current freeze")
    ok, detail = check_gold(root, build_dir)
    if not ok:
        problems.append(f"gold replay: {detail}")
    ok, detail = check_policy(root, expected_record_sha256=impl.get("policy_record_sha256"))
    if not ok:
        problems.append(f"grading policy: {detail}")
    if problems:
        raise GateError("; ".join(str(p) for p in problems))
    return {"implementation_sha256": _sha(impl_path), "rubric_sha256": impl["rubric"]["sha256"], "rubric_version": impl["rubric_version"],
            "gold_manifest_sha256": impl["gold_manifest_sha256"], "policy_record_sha256": impl["policy_record_sha256"],
            "freeze_sha256": freeze_sha(root)}
