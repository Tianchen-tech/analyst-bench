# Changes after Pilot-1

The Pilot-1 results were produced with the private harness and published together with the public copy of it at commit [`1910d3d`](https://github.com/Tianchen-tech/analyst-bench/tree/1910d3d242205687505f2380bd79d08cf1aa82d1). The changes below were made afterwards and apply to future rounds.
- The Pilot-1 results, reports and dashboards were not regenerated, and every published number is unchanged.
- `tools/recompute_public.py` checks those numbers against the results files.
- The task files are byte-identical to the release, and a test keeps them that way.

## 2026-11-03

### Scoring and judging

- **Warning links** (`harness/grader/score.py`): a warning whose `result_paths` pointer names a value inside a claim's record now links to that claim. For example, `/result/drivers/0/contribution` links to the driver claim `/result/drivers/0`. The task contract allows a pointer to a single value; before, only the claim's own location or its containing record linked. `linked_warnings` is shown to judges as a hint, and judges still decide whether a warning qualifies the claim. A line that did nothing was removed.
- **Private modules** (`harness/grader/score.py`): the task-specific `atoms` and `tasks` modules are not published. They are now imported only when a provisional record is built, so `score`, `review` and `aggregate` can be imported and tested without them.
- **Ties** (`harness/judge/judge.py`): `_majority` now gives a tie to the first value in the given order. Before, it used set iteration order, which changes with `PYTHONHASHSEED`. Published results did not depend on this: `scripts/panel_combine.py` replaced every tied claim by the lenient/strict rule and stopped on any other tie.
- **Legacy judge call** (`harness/judge/judge.py`): removed the unused wave-1 Grok-only `call()`, which inherited the caller's whole environment. Judge calls go through `backends.py`, which uses a minimal environment.

### Runner

- **Kill routine** (`harness/runners/controller.py`): processes are now tracked by pid and start time.
  - At the time limit, a tracked process is signalled only while its start time still matches. A pid reused by an unrelated process is never signalled.
  - Members of the run's process group are included, and survivors are counted the same way; zombies are not counted.
  - Still a limit: a process that leaves both the process tree and the process group between two polls is not tracked. A per-run user account or a VM would close that gap.
- **Proxy** (`harness/runners/proxy.py`): after an accepted CONNECT, the tunnel must start with a TLS ClientHello whose server name (SNI) equals the CONNECT host.
  - A ClientHello without a server name, or with an encrypted ClientHello (ECH), is refused.
  - Each tunnel logs its byte counts when it closes, and the egress summary adds `bytes_up` and `bytes_down`.
  - A request head that is never terminated is refused with 403 instead of raising an error. The upstream socket is closed explicitly.
  - The proxy does not decrypt traffic, so a CDN that honoured a Host header different from the SNI stays outside what it can check.
- **Claude Code adapter** (`harness/runners/adapters/claude_code_print.py`): removed `observed.effort_requested`, which was always `"high"` whatever the settings said. The requested level is recorded from the product settings in `identity.reasoning_setting`.
- **Replay** (`harness/grader/replay.py`): macOS `libproc` is loaded on first use, still before any replay process starts, so the module also imports on other systems.

### Documentation

- Corrected stale docstrings in `harness/scripts/preflight.py` (wave 2 uses Antigravity CLI), `harness/grader/run_bundle.py` (products per wave) and `harness/runners/wave.py` (report path).
- Annotated the first-version product table in `reports/runner_and_preflight.md`: `--ephemeral` was dropped and the allowlists were narrowed after the smoke run.
- README: added a note on the `"task_id": "Q01"` placeholder in the task statements, how to check the published numbers, and the license.

### Added

- `LICENSE` (MIT, for the code) and `LICENSE-CONTENT` (CC BY 4.0, for everything else).
- `tools/recompute_public.py`: recomputes the published metrics and checks the README, methodology, reports, findings and both dashboards against them. `--write-dashboard` regenerates the data block of `docs/index.html`.
- `tests/`, with pytest settings in `pyproject.toml` and test dependencies in `requirements-dev.txt`.
- A GitHub Actions workflow that runs the check and the tests on Linux and macOS.
