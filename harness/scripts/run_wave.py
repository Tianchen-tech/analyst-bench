"""Pilot-1 formal wave: run the 36 scheduled slots of the certified run bundle (private/runners/wave.py).

    python scripts/run_wave.py --dataset generated/pilot                 # run/resume in bundle order; waits for quota resets
    python scripts/run_wave.py --dataset generated/pilot --max-slots 1   # stop after one slot
    python scripts/run_wave.py --dataset generated/pilot --no-wait       # exit instead of waiting for a reset
    python scripts/run_wave.py --status                                  # progress only (no results)
    ... --wave 2                                                          # wave 2 (Grok Build, Antigravity; ID-49)
    python scripts/run_wave.py --dataset generated/pilot --acknowledge "REASON"   # owner: cause of a stop fixed; continue
    python scripts/run_wave.py --dataset generated/pilot --accept-driver-change "REASON"   # owner: continue on a changed driver

Run on the host (sandbox-exec cannot be nested). Ctrl-C during a run lets it finish, then stops; rerunning resumes from
the ledger (private/runs/wave/ledger.jsonl). Do not open private/runs/wave/slots/*/outputs before the wave is complete.
Exit codes: 0 complete, stopped or slot limit reached; 4 the wave stopped for the owner; 5 waiting for a reset (--no-wait).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runners import wave


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path)
    ap.add_argument("--max-slots", type=int)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--acknowledge", metavar="REASON", help="owner acknowledgement of a repeated-infrastructure stop")
    ap.add_argument("--accept-driver-change", metavar="REASON", help="owner acceptance of a changed wave driver (recorded)")
    ap.add_argument("--wave", default="1", choices=sorted(wave.WAVES), help="1: Codex/Claude Code; 2: Grok Build/Antigravity (ID-49)")
    a = ap.parse_args()
    wave_dir, bundle_path = wave.WAVES[a.wave]
    if a.status:
        print(json.dumps(wave.status(wave_dir, bundle_path), indent=1, default=str))
        return 0
    if a.dataset is None:
        ap.error("--dataset is required")
    print("Pilot-1 wave: outputs are sealed until the wave is complete; do not open slot outputs.", flush=True)
    w = wave.Wave(a.dataset.resolve(), wave_dir=wave_dir, bundle_path=bundle_path, wave=a.wave, say=lambda m: print(m, flush=True))
    if a.acknowledge is not None:
        w.acknowledge(a.acknowledge)
        print("acknowledged; rerun without --acknowledge to continue the wave", flush=True)
        return 0
    try:
        result = w.run(max_slots=a.max_slots, wait=not a.no_wait, accept_driver_change=a.accept_driver_change)
    except wave.WaveStop as exc:
        w.ledger.append("wave_stop", reason=str(exc))
        print(f"WAVE STOPPED FOR THE OWNER: {exc}", file=sys.stderr, flush=True)
        return 4
    print(json.dumps(wave.status(wave_dir, bundle_path), indent=1, default=str), flush=True)
    return 5 if result == "waiting" else 0


if __name__ == "__main__":
    sys.exit(main())
