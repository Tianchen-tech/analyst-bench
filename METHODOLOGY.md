# Pilot-1 methodology

This document describes how Pilot-1 was run and scored. Decisions made during the pilot are listed at the end with their timing, so readers can judge which ones were made after results were seen.

## 1. Tasks and data

- **Dataset:** a synthetic strategy mobile game warehouse in one DuckDB file: 300,000 accounts, 15 servers, eight raw tables and 26 observed weeks. The extraction date is July 10, 2025. The data is generated deterministically from a seed, with planted analytical traps. Examples: duplicate ingestion, minor-unit currency rows, late-arriving events, GM test accounts, refunds of earlier purchases, a sample-ratio-mismatched A/B test, Simpson's-paradox channel mix and payer concentration.
- **Tasks:** nine of the 28 designed tasks were used in Pilot-1. Seven are core analysis tasks. Two (Q26, Q27) are unanswerable from the data and test abstention.
- **What the agent sees:** the agent sees only `task.md` (request, calendar, currencies, metric and business definitions, and the execution contract) and the database. The answer format is a schema-validated `answer.json` (structured metrics, claims, warnings, assumptions and evidence pointing at saved files) plus a 150–400-word `memo.md`.
- **Opening prompt:** identical for every product. It asks the agent to read `task.md`, use SQL or Python, write both files, keep reproducible scripts, and work independently within 20 minutes.

## 2. Products and settings

| Product | Interface | Model and effort | Authentication |
|---|---|---|---|
| Codex | `codex exec` 0.160.0 | `gpt-6.1-sol`, reasoning high | ChatGPT Plus subscription |
| Claude Code | `claude -p` 2.1.289 | `claude-opus-5-5`, effort high | Claude Pro subscription |
| Grok Build | `grok -p` 1.0.40 | `grok-4.7`, reasoning high | grok.com subscription |
| Antigravity CLI | `antigravity -p` 1.2.16 | `gemini-3.8-flash-high` | Google AI Pro subscription |

**Common settings:**
- All products used subscription allowance only. No API keys were present, and no paid usage was enabled.
- Web search was disabled where the product allows it. Antigravity's server-side `search_web` could not be disabled; every query was logged, and there were 0 in the scored attempts.
- Each run used a fresh product profile containing only credentials, with no user settings, memory or MCP servers.
- Product versions, executable hashes, settings snapshots and the observed model were recorded per run and checked against a frozen run bundle.

## 3. Isolation and run control

**Per run:**
- **Staging:** each run gets a fresh root with `work/` (exactly `task.md` and a read-only database copy, hash-verified), a disposable `home/` and `tmp/`.
- **Sandbox:** macOS `sandbox-exec` allows file reads only from system locations, the product install, the shared analysis environment and the run root, and file writes only inside the run root.
- **Network:** only the controller's allowlist proxy is reachable. It accepts HTTPS CONNECT to the product's inference and authentication hosts; everything else is denied and logged. Product background traffic, such as analytics or feature flags, is denied and recorded apart from agent access.
- **Canary:** a file outside `work/` must be unreadable before every run.
- **Time cap:** 1,200 s of wall clock, then the whole process tree is killed. Outputs are snapshotted after the kill.

**Preflight:** before each wave, every product ran two toy tasks twice, plus one forced-timeout check and one blocked-download check. The run records had to pass on the same runner code and settings that the wave used.

**Schedule:**
- Strict bundle order, with seed 20260931. Tasks are shuffled within each repetition, and product order alternates by block.
- An append-only ledger allows stopping and resuming without rerunning or skipping anything.
- Before every slot, the driver re-verifies the bundle, the runner code and the product binary hash.

**Failure policy:**
- A timeout, empty output or refusal is a result and is never replaced.
- An evidenced infrastructure event (for example quota exhaustion or an interrupted run) gets one replacement after the provider's reset. Both records are kept.

**Known limits:**
- one shared host kernel, on the owner's machine rather than a VM;
- Antigravity's sandbox additionally allowed localhost for its own language server.

## 4. Scoring

1. **Intake:**
   - every file is archived with hashes;
   - `answer.json` is parsed strictly against the task schema;
   - evidence paths must be submitted files or the provided inputs.
2. **Automatic atoms:** structured metrics are mapped to the answer key through a typed alias matcher, which checks scope, horizon, denominator, unit and time window. Numbers are compared at fixed tolerances (USD to the cent, ratios to 1e-4, counts exactly). For the extract task, submitted SQL is replayed in a restricted sandbox (no network, no process creation, read-only data, time and memory limits).
3. **Review items:** qualitative atoms (for example, "a conditional recommendation without unsupported causal claims"), every claim's verdict (correct, wrong, immaterial or unverifiable), whether a wrong claim was warned, critical errors, caps and trap detection. A value an agent reported outside the structured fields goes to review rather than counting as wrong.
4. **Finalize:** score, caps, critical failure and success. A successful delivery requires a completed outcome, a score of at least 80 with no critical error for core tasks, or at least 75 with no invented answer for unanswerable tasks. Timeout/error outputs keep their content scores but cannot succeed under the pre-registered design.
5. **Aggregate** (per product):
   - core accuracy;
   - valid abstention;
   - trap recall;
   - E, the share of substantive answers with a wrong material claim;
   - S, the share with a wrong claim and no linked warning;
   - completion;
   - time.

**Speed-adjusted score (secondary):** passing attempts get `score × (1 + 0.10 × (1 − seconds / 1200))`. Failing attempts keep their score, so fast wrong answers earn nothing.

## 5. Judging

- **Panel:** judges from GPT (via Codex), Claude (via Claude Code) and Grok (via Grok Build). Gemini was unavailable as a judge.
- **Assignment (leave-own-provider-out):** each blind answer is judged once by every judge from a different vendor than its author. That gives two judges for Codex, Claude Code and Grok Build answers, and three for Antigravity.
- **What judges get:**
  - the exact task text, the private reference for that task, the anonymized answer (product names masked) and the list of required decisions;
  - no tools, web or subagents, in a fresh session each time.
- **Validation:**
  - every judgment is checked for completeness and repaired at most twice;
  - r4 retains the original semantic objection separately from effective arithmetic. Unresolved objections prevent finalization; a recorded versioned adjudication binds the exact original notes and current policy. Original judge-v1 calls and r3 records remain unchanged.
- **Combination:**
  - three judges: majority, with the median for points; memo warnings also need affirmative support from a majority of the full eligible panel;
  - two judges: two versions:
    - **lenient:** the reading more favorable to the answer counts;
    - **strict:** the less favorable reading counts. Memo errors use the same intersection/union and any/all warning rules as structured claims.
  - Both versions are reported.
- **Agreement:** the repaired counter finds 41/72 original saved panels with material disagreements (rather than the r3 report's 38). The derived r4 panels have 40/72; these are different decision versions. Current lenient/strict delivery success differs in 1/72 attempts. Rule sensitivities are not statistical confidence intervals.

## 6. Decisions made during the pilot

| When | Decision | Seen before deciding |
|---|---|---|
| Before wave 1 | Subscription-only budget; reasoning effort high for all products; host sandbox instead of a VM | Toy preflights only |
| During wave 1 | Quota pause changed from an 80% gate to "pause only when exhausted" | Run times, no scores |
| After wave 1 provisional scoring | Owner review replaced by an AI judge (workload: 722 claim verdicts) | Provisional automatic scores |
| Same time | A citation of the provided `task.md` counts as valid evidence | Two affected answers |
| After wave-1 results by product | ISO interval notation `[start, end)` read correctly; this restored 20 points on each Codex Q07 answer | Wave-1 results |
| Same time | A leave-own-provider-out panel replaces the single judge; wave 1 re-judged | Wave-1 results |
| Before wave 2 | Gemini CLI replaced by Antigravity CLI (Google rejects personal accounts for Gemini CLI); Antigravity's web search kept with disclosure | Toy preflights |
| During wave 2 | Secondary speed-adjusted score, capped at +10% | Some wave-2 times, no wave-2 scores |
| After all judging | Two-judge disagreement reported as lenient and strict | Disagreement counts by product, no scores |
| October 5, after all results | r4 semantic identity, warning combination, recorded-dispute and terminal-outcome repair; all preserved outputs regraded | All original results and judgments |

**Resolved in r4, after results were visible:** the timeout is an unsuccessful delivery. Content scores remain visible, and accuracy, throughput, repeat agreement and successful-time medians all use the same delivery-success predicate. All 72 preserved outputs were regraded uniformly; no new contestant or judge call was made.

## 7. Scope of the r4 repair

This correction is AI audit work, not a new blinded human assessment. Original eligible judgments are carried forward, and changes are recorded with their source hashes. Newly exposed partial-credit items use explicit archived evidence; unsupported supplementary claims are not called correct just because a spurious reference comparison was removed. Wrong scope remains a delivery error. The demonstrated unrelated rounding/gross warning does not qualify that scope error. Other qualitative judgments retain the original panel's limitations.

The 49 corrected metric identities are covered by regressions across all 72 archived answers and 1,358 metrics. Original source files, 162 judgments, r3 finals and historical aggregates remain preserved. The current local scoring gate binds r4 modules, policy, references and runtime; the original collection bundle remains historical evidence of the conditions used when the agents ran.
