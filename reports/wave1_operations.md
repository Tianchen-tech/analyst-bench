# Pilot-1 wave 1: operational report (no results)

**Status:** complete. All 36 scheduled slots are resolved. Grading has not started, and nothing in this report reads or summarizes answers or memos.

## Run

- **Bundle:** `f82703f6…` (`pilot1-bundle-v2`, EVALUATION_READY).
- **Time:** started 2026-10-04 04:11:28Z, complete at 08:19:09Z.
- **Ledger:** `private/runs/wave/ledger.jsonl`, 84 lines, sha256 `ee8b7ed36cecfc756ef0c5c7e77bed2f4f9cc7b199335dfda2667620aab014f0`. It is annotated in `private/grading/wave1_ledger_annotations.json`.
- **Attempts:** 36 analytical attempts plus one labelled original (slot 24, an infrastructure/availability event). All 36 analytical attempts ended with the product exiting and both output files present: no timeouts, no empty outputs, and no owner-review flags on them.
- **Integrity:** checked on all 37 controller records. Every record has a passing canary, an unchanged database and task file, 0 processes left, and 0 agent external-access attempts. Codex's known product background requests to `*.oaiusercontent.com` were denied, 17 per run. The bound runner, runtime settings, executable, version and model held on every record (`gpt-6.1-sol` and `claude-opus-5-5`), with no drift.

**Elapsed time over the 18 analytical attempts per product:**

| Product | Min | Median | Max | Total |
|---|---|---|---|---|
| Codex | 125 s | 331 s | 704 s | 110.6 min |
| Claude Code | 53 s | 116 s | 211 s | 35.8 min |

**Quota:**
- Claude Code's five-hour window ran out once, at slot 24. That slot was replaced after the 07:00Z reset.
- Weekly use at the end: Claude 32%, Codex 23%.
- Paid overage stayed `rejected` / not in use throughout.

## Incident: stale driver process (slot 24)

**What happened:**
1. The owner accepted a new driver at 05:25Z, which removed the early quota stop (ID-46).
2. The earlier driver process was still waiting in another terminal tab, in its 80% quota wait since 05:10Z, and was never stopped.
3. That process woke after the 07:00Z reset and, at 07:02:31Z, tried slot 24's replacement. The current driver had started that replacement at 07:00:33Z.
4. The stale attempt was refused by the controller's first check (output directory not empty), before staging or any product start. The stale process then logged an infrastructure slot end and a `wave_stop` for itself and exited.
5. The current driver finished the replacement normally and completed the wave.

**Effect:** no contestant run was affected. The ledger keeps the stale lines (append-only); the annotations mark them as not an attempt and not a wave stop.

**Fix:**
- The driver now holds an exclusive lock on the wave directory.
- Before every slot it re-reads the ledger and stops if it is not the current driver or if the slot is already open.
- Three new tests cover this (23 wave tests pass).

## Deviations to disclose

- **Repetition timing:** r1 and r2 ran on the same day, back to back. Design 6.5 says "preferably different days".
- **Quota gates changed mid-wave** by owner instruction, through a recorded driver change. Slots 0–10 ran under the earlier gates, which paused the wave once. Contestant settings were unaffected.
- **Shared Claude allowance:** Claude Code's allowance was shared with the operator's own Claude session.

## Next

Provisional scoring of the 36 analytical attempts (`scripts/grade.py provisional`), then the blind review packets for the owner, then finalize and aggregate.
