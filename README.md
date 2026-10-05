# Analyst Bench

Analyst Bench is a benchmark for AI analyst agents on realistic product-analytics questions. Each agent gets a business request, a synthetic mobile-game data warehouse in DuckDB and 20 minutes. It must answer in a structured `answer.json` plus a short memo, and save the code that reproduces its numbers.

This repository publishes **Pilot-1**: four agent products, nine tasks, two independent attempts per task. It includes the task statements, the evaluation harness, the judging protocol, the results and the dashboard. The answer key is withheld so the task set stays usable for future rounds (see [What is not published](#what-is-not-published)).

**Dashboard:** [`docs/index.html`](docs/index.html). Serve it with GitHub Pages, or open it locally.

## Pilot-1 results

**Setup:**
- **Products:** Codex (`gpt-6.1-sol`, reasoning high), Claude Code (`claude-opus-5-5`, high), Grok Build (`grok-4.7`, high) and Antigravity CLI (`gemini-3.8-flash-high`).
- **Attempts:** 18 per product (9 tasks × 2), each in a fresh session inside a local sandbox.
- **Original judging:** answers were judged by AI judges from the *other* vendors. Where two judges disagree, original r4 results are shown as **lenient | strict**. A separate post-results check now gives every answer GPT, Claude and Grok judges, including its own provider where applicable.

**Shared-panel check:** 54 additional blind reviews complete 216 reviews of the same 72 answers. Shared-panel means are Codex **99.60**, Claude Code **83.73**, Grok Build **81.82**, Antigravity **83.00**. Core successes are **14/14, 10/14, 9/14, 7/14**; silent errors are **0/18, 5/18, 6/18, 14/18**. The mean-score and core-accuracy orderings are unchanged, but several silent-error labels change. Equal judge assignment does not prove unbiased grading or zero true errors; five statements retain exact three-way splits. See the [comparison and limitations](results/REPORT.md#what-changed-with-the-same-judges-for-every-product) and [aggregate comparison](results/pilot1_shared_panel_comparison.json).

The table and dashboard charts below retain the **original r4 baseline**:

| Metric | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| Core accuracy (7 tasks × 2) | 14/14 | 10/14 | 9/14 \| 8/14 | 7/14 |
| Valid abstention (Q26, Q27) | 4/4 | 4/4 | 3/4 | 2/4 |
| Trap recall | 22/22 \| 21/22 | 19/22 | 20/22 | 18/22 |
| Attempts with a wrong material claim (E) | 0/18 \| 2/18 | 6/18 \| 12/18 | 5/18 \| 9/18 | 15/18 |
| Silent errors (S) | 0/18 \| 2/18 | 2/18 \| 11/18 | 4/18 \| 9/18 | 14/18 |
| Mean saved-content score | 100.00 \| 97.89 | 83.73 \| 82.76 | 81.82 \| 79.74 | 83.00 |
| Speed-adjusted mean (≤ +10%) | 106.93 \| 104.68 | 90.72 \| 89.73 | 84.50 \| 82.30 | 86.88 |
| Median seconds, all attempts | 331 | 116 | 849 | 275 |
| Median seconds, successful deliveries | 331 | 107 | 685 \| 551 | 243 |
| Successful deliveries per agent hour | 9.77 | 23.44 | 3.07 \| 2.81 | 6.60 |
| Same delivery success in both repetitions | 9/9 | 7/9 | 7/9 \| 6/9 | 8/9 |
| Terminal failures / format failures | 0 / 0 | 0 / 0 | 1 / 0 | 0 / 0 |

**Findings:**

- Codex passed every core task in both repetitions in this pilot. Its r4 error labels exclude the demonstrated evaluator identity mistakes.
- Claude Code had the shortest median runtime and the most successful deliveries per agent hour.
- Grok Build had the longest median runtime. Its timeout keeps the saved-content score and counts as an unsuccessful delivery.
- Antigravity's error incidence remains high under the original majority panel; this is one small synthetic pilot.

**Correction version:** scorer r4, applied after all results were visible. All 72 outputs were regraded using the same frozen data and original 162 judgments, with explicit source-bound repair decisions. No contestant rerun or new judging call was made. Unsupported supplementary metrics remain unverifiable unless their own quantity was independently checked. Original r3 results are in [`results/history/r3/`](results/history/r3).

**Error patterns:** [`FINDINGS.md`](FINDINGS.md) (dashboard: [`docs/findings.html`](docs/findings.html)) describes the five recurring ways the agents went wrong, with real cases and a review checklist. The short version: the agents found data problems well, but finding a problem did not reliably stop them from overstating their conclusions.

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

## Running the tasks yourself

The task statements, results and error cases in this repository are public, so an agent with web access could look up what each task tests. If you run these tasks on an agent:

- turn off web search and URL fetching for the agent;
- ideally allow network access only to the model's own inference endpoint, as the Pilot-1 harness did (see `harness/runners/proxy.py`);
- if a product's server-side search cannot be switched off, record and report every search it makes.

Treat any new scores as a fresh run on known tasks, not as a continuation of Pilot-1. The dataset is not included in this repository.

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
   - arithmetic is protected after checking metric identity; semantic objections require a versioned resolution and remain visible.
4. **Metrics:** core accuracy, valid abstention, trap recall, error and silent-error incidence, and time. A secondary speed-adjusted score rewards correct answers only.

## Repository layout

| Path | Contents |
|---|---|
| `tasks/` | The nine task statements, answer schemas, business definitions and the execution contract given to agents |
| `harness/runners/` | Sandbox controller, allowlist proxy, wave driver and product adapters |
| `harness/judge/` | Judge protocol (the exact instructions judges receive), prompt builder, validation and consensus, judge backends |
| `harness/grader/` | Scorer core: intake, finalize and review, aggregation, SQL replay sandbox, run-bundle validator |
| `harness/scripts/` | The command-line entry points used to run preflights, waves, grading, judging and the final aggregation |
| `FINDINGS.md` | Error patterns across the 72 answers, with cases and reviewer checks |
| `results/` | Preserved r4 results (`pilot1_four_products.json`), a separate shared-panel aggregate comparison and the results report |
| `reports/` | Operational reports: runner build and preflight, wave-1 operations and incidents |
| `docs/` | The results dashboard (`index.html`) and the error-pattern dashboard (`findings.html`) |

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

## How this project was built

The benchmark was built with AI models working in three roles, under the direction of the project owner:

- **Framework:** GPT-6-Astra designed the overall project framework.
- **Implementation:** Claude Opus 5.5 (`claude-opus-5-5`, through Claude Code) built each concrete step. This included the data generator, the tasks and reference answers, the scorer, the sandbox harness, the judging pipeline, and the reports and dashboards.
- **Audit:** GPT-6.1-sol (`gpt-6.1-sol`, through Codex) audited each step before it was accepted. About 30 written review and audit reports are kept in the private repository.

The owner set the direction and made the protocol decisions recorded in [`METHODOLOGY.md`](METHODOLOGY.md).

**Conflict of interest:** two of these models are also the models behind two of the products under test:
- Claude Code ran `claude-opus-5-5`, the implementing model.
- Codex ran `gpt-6.1-sol`, the auditing model.

The models behind Grok Build and Antigravity had no building role. Grok served only as a judge.

**What limits the effect:**
- Contestant runs used fresh profiles with no memory, no project files and no access to the build sessions.
- Reference answers are computed from the data generator, not from model judgement.
- Judging used other vendors' models.

**What it does not rule out:** the tasks, rubrics and reference answers may still reflect how these two models frame an analysis, and that could favor their products. No independent human review has checked for this.

## Disclosures

The evaluation protocol changed during the pilot, and each change is recorded with its timing and reason:
- the review moved from planned owner review to an AI judge panel;
- two grader fixes were made after wave-1 results were seen;
- r4 corrected evaluator defects after all results were visible, reusing preserved outputs and judging records;
- a later shared-panel comparison added 54 blind reviews after results were visible; it preserves the original r4 result and documents remaining splits;
- a secondary speed bonus was added during wave 2;
- Antigravity's server-side web search could not be disabled; it was used 0 times in scored attempts;
- Gemini CLI could not be used with a personal Google account, so Antigravity CLI is the Google product.
- the models that implemented and audited the benchmark are also the models behind Claude Code and Codex (see [How this project was built](#how-this-project-was-built)).

See [`results/REPORT.md`](results/REPORT.md) and [`METHODOLOGY.md`](METHODOLOGY.md).
