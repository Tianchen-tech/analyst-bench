# Analyst Bench

Analyst Bench is a benchmark for AI analyst agents on realistic product-analytics questions. Each agent gets a business request, a synthetic mobile-game data warehouse in DuckDB and 20 minutes. It must answer in a structured `answer.json` plus a short memo, and save the code that reproduces its numbers.

This repository publishes **Pilot-1**: four agent products, nine tasks, two independent attempts per task. It includes the task statements, the evaluation harness, the judging protocol, the results and the dashboard. The answer key is withheld so the task set stays usable for future rounds (see [What is not published](#what-is-not-published)).

**Dashboard:** [`docs/index.html`](docs/index.html). Serve it with GitHub Pages, or open it locally.

## Pilot-1 results

**Setup:**
- **Products:** Codex (`gpt-6.1-sol`, reasoning high), Claude Code (`claude-opus-5-5`, high), Grok Build (`grok-4.7`, high) and Antigravity CLI (`gemini-3.8-flash-high`).
- **Attempts:** 18 per product (9 tasks × 2), each in a fresh session inside a local sandbox.
- **Judging:** answers were judged by AI judges from the *other* vendors. Where two judges disagree, results are shown as **lenient | strict**.

| Metric | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| Core accuracy (7 tasks × 2) | **14/14** | 10/14 | 9/14 \| 8/14 | 7/14 |
| Unanswerable tasks handled (Q26, Q27) | 4/4 | 4/4 | 3/4 | 2/4 |
| Trap recall | 22/22 \| 21/22 | 19/22 | 20/22 | 18/22 |
| Answers with a wrong material claim | 2 \| 4 /18 | 7 \| 13 /18 | 7 \| 10 /18 | 15/18 |
| Silent errors (wrong and unwarned) | 2 \| 4 /18 | 3 \| 11 /18 | 4 \| 9 /18 | 14/18 |
| Mean score | 100.0 \| 97.9 | 83.7 \| 82.8 | 79.0 \| 76.9 | 81.6 |
| Speed-adjusted score (≤ +10%) | 106.9 \| 104.7 | 90.7 \| 89.7 | 81.5 \| 79.3 | 85.5 |
| Median time per attempt | 331 s | **116 s** | 849 s | 275 s |
| Correct answers per agent hour | 9.8 | **23.4** | 3.1 \| 2.8 | 6.6 |

**Findings:**
- **Codex** was the most accurate and the most consistent. It passed every core task in both attempts.
- **Claude Code** was about three times faster than Codex and had the most correct answers per hour. Its failures concentrate on one task (Q14).
- **Grok Build** was the slowest. One attempt hit the 20-minute cap.
- **Antigravity** had the most wrong claims.

With 18 attempts per product on one dataset, these are descriptive results, not statistical claims. The full report with per-task scores and every disclosure is in [`results/REPORT.md`](results/REPORT.md).

## The tasks

The dataset is a synthetic strategy mobile game warehouse:
- **Size:** 300,000 accounts on 15 servers, with eight raw tables.
- **Period:** 26 weeks, with an extraction date of July 10, 2025.
- **Realistic defects:** duplicate ingestion, minor-unit currency rows, late-arriving data, GM test accounts, refunds of earlier purchases, a broken A/B allocation and others.

The nine Pilot-1 tasks are in [`tasks/`](tasks). Each task folder holds the exact `task.md` the agent saw and the JSON schema its answer must follow.

| Task | Request | Kind |
|---|---|---|
| Q03 | S15 week-8 gross bookings, refunds and net bookings | core |
| Q04 | Exact-day D7 retention of an S03 cohort by platform | core |
| Q07 | Reusable 26-week bookings extract that reconciles with finance | core |
| Q12 | Why cash and returning players dropped on S04 in week 14 | core |
| Q14 | Whether channel C's week-6 ARPU is a usable acquisition signal | core |
| Q16 | Which channel comparison should guide the S02 budget | core |
| Q17 | Whether a finished price test supports shipping offer B | core |
| Q26 | Why one customer requested a large refund | unanswerable |
| Q27 | The final D180 LTV of June cohorts | unanswerable |

The unanswerable tasks test whether an agent says what the data cannot establish instead of inventing an answer.

## How the evaluation works

See [`METHODOLOGY.md`](METHODOLOGY.md) for the full protocol. In short:

1. **Isolation:**
   - every attempt runs in a fresh directory that holds only `task.md` and a read-only copy of the database;
   - the agent runs under macOS `sandbox-exec`, and its network goes only through an allowlist proxy to its own inference service;
   - a canary file outside the work directory must stay unreadable;
   - a hard 1,200 s cap kills the whole process tree.
2. **Schedule:** each run follows a pre-registered, seeded schedule recorded in a hash-bound run bundle. Version or setting drift stops the run.
3. **Grading:**
   - a deterministic scorer checks the structured numbers against the hidden answer key and replays submitted SQL in a restricted sandbox;
   - AI judges from other vendors decide the remaining review items, such as whether a recommendation is properly qualified, whether a claim is wrong, and whether it was warned;
   - automatic arithmetic verdicts are never overridden by a judge.
4. **Metrics:** core accuracy, valid abstention, trap recall, error and silent-error incidence, and time. A secondary speed-adjusted score rewards correct answers only.

## Repository layout

| Path | Contents |
|---|---|
| `tasks/` | The nine task statements, answer schemas, business definitions and the execution contract given to agents |
| `harness/runners/` | Sandbox controller, allowlist proxy, wave driver and product adapters |
| `harness/judge/` | Judge protocol (the exact instructions judges receive), prompt builder, validation and consensus, judge backends |
| `harness/grader/` | Scorer core: intake, finalize and review, aggregation, SQL replay sandbox, run-bundle validator |
| `harness/scripts/` | The command-line entry points used to run preflights, waves, grading, judging and the final aggregation |
| `results/` | Final results (`pilot1_four_products.json`) and the results report |
| `reports/` | Operational reports: runner build and preflight, wave-1 operations and incidents |
| `docs/` | The results dashboard |

## What is not published

The following are withheld so the task set can be reused for future rounds:
- the reference answers and replayable reference SQL;
- the task-specific scoring rules and the metric-alias registry;
- the data generator, which encodes every planted defect and its true effect;
- the full design document;
- the judge prompts and raw judgments, which contain the reference answers;
- the agents' raw answers and transcripts.

The 342 MB DuckDB file is not in this repository either.

Because of this, the harness here documents exactly how the evaluation ran, but it cannot reproduce the scores end to end on its own.

## Disclosures

The evaluation protocol changed during the pilot, and each change is recorded with its timing and reason:
- the review moved from planned owner review to an AI judge panel;
- two grader fixes were made after wave-1 results were seen;
- a secondary speed bonus was added during wave 2;
- Antigravity's server-side web search could not be disabled; it was used 0 times in scored attempts;
- Gemini CLI could not be used with a personal Google account, so Antigravity CLI is the Google product.

See [`results/REPORT.md`](results/REPORT.md) and [`METHODOLOGY.md`](METHODOLOGY.md).
