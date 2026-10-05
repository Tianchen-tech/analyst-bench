"""Grade a completed Pilot-1 wave: provisional records for every analytical attempt, blind packets, the attempts list.

    python scripts/grade_wave.py --dataset generated/pilot [--skip-host-only]   # provisional + packets + attempts.json
    python scripts/grade_wave.py --dataset generated/pilot --only Q07          # e.g. the host-only Q07 replays
    ... --wave 2                                                               # wave 2 slots (ID-49)

Each attempt goes through the unchanged scorer CLI (`scripts/grade.py provisional`), one fresh output directory per
attempt under private/grading/wave1/<run_id>/. The reviewer folder private/review/wave1/ receives only the packets,
named by pseudonym, plus an index without products, repetitions, run ids or slot order. Q07 transformation replays run in
the restricted replay, which needs the host (sandbox-exec cannot be nested); `--skip-host-only` leaves them for a host run.
Infrastructure originals (no output) enter attempts.json with dir null. The stale-driver ledger lines annotated in
private/grading/wave1_ledger_annotations.json have no slot directory and are not attempts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAVES = {"1": ("wave", "wave1"), "2": ("wave2", "wave2")}       # runs dir, grading/review dir (wave 2: ID-49)
HOST_ONLY_TASKS = {"Q07"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--skip-host-only", action="store_true")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--wave", default="1", choices=sorted(WAVES))
    a = ap.parse_args()
    global SLOTS, OUT, REVIEW
    SLOTS = ROOT / "private" / "runs" / WAVES[a.wave][0] / "slots"
    OUT = ROOT / "private" / "grading" / WAVES[a.wave][1]
    REVIEW = ROOT / "private" / "review" / WAVES[a.wave][1]
    only = set(a.only.split(",")) if a.only else None
    slots = [json.loads(p.read_text()) | {"_dir": p.parent} for p in sorted(SLOTS.glob("*/slot.json"))]
    attempts, results = [], []
    for s in slots:
        slot = {k: s[k] for k in ("run_id", "task_id", "product", "repetition")} | {"replacement": int(bool(s["replacement"]))}
        out = OUT / s["run_id"]
        graded = s["outcome"] != "infrastructure" and (s["_dir"] / "outputs").is_dir()
        attempts.append({"slot": slot, "outcome": s["outcome"], "dir": str(out) if graded else None})
        if not graded or (only and s["task_id"] not in only):
            continue
        if (out / "provisional.json").exists():
            results.append({"run_id": s["run_id"], "status": "already graded"})
            continue
        if a.skip_host_only and s["task_id"] in HOST_ONLY_TASKS:
            results.append({"run_id": s["run_id"], "status": "skipped: host-only replay"})
            continue
        run = OUT / "_run" / f"{s['run_id']}.json"
        run.parent.mkdir(parents=True, exist_ok=True)
        run.write_text(json.dumps(slot | {"outcome": s["outcome"]}))
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "grade.py"), "provisional", "--dataset", str(a.dataset),
                            "--run", str(run), "--submission", str(s["_dir"] / "outputs"), "--out", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            results.append({"run_id": s["run_id"], "status": f"FAILED rc={r.returncode}", "stderr": r.stderr[-800:]})
            if out.exists() and not (out / "provisional.json").exists():
                shutil.rmtree(out)                       # nothing sealed: leave no half-written directory behind
            continue
        results.append({"run_id": s["run_id"], "status": "graded"})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "attempts.json").write_text(json.dumps(attempts, indent=1) + "\n")
    index = []
    for d in sorted(OUT.glob("*/packet.json")):
        pk = json.loads(d.read_text())
        dest = REVIEW / "packets" / f"{pk['pseudonym']}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(d, dest)
        index.append({"pseudonym": pk["pseudonym"], "task_id": pk["task_id"]})
    index.sort(key=lambda x: (x["task_id"], x["pseudonym"]))
    if index:
        (REVIEW / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    summary = {"attempts": len(attempts), "graded_dirs": sum(1 for x in attempts if x["dir"]),
               "this_run": {k: sum(1 for r in results if r["status"].startswith(k)) for k in ("graded", "already", "skipped", "FAILED")},
               "packets": len(index), "failures": [r for r in results if r["status"].startswith("FAILED")]}
    print(json.dumps(summary, indent=1))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
