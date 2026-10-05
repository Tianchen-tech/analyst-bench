# Where AI analyst agents go wrong: error patterns from Pilot-1

**The main finding:** the agents in this pilot were good at *finding* problems in the data. Finding a problem did not reliably stop them from overstating what the data could support. Most serious errors were not wrong arithmetic. They were conclusions that went past the evidence: a correct analysis of the wrong population, a causal effect claimed from an experiment the agent had just called invalid, a customer's motive invented from a payment log, or a budget forecast read off historical averages.

An interactive version of this report is in [`docs/findings.html`](docs/findings.html).

**October 5 update:** the same 72 answers now also have a shared three-judge comparison. It leaves the core-performance ordering intact but changes several silent-error labels. The original r4 taxonomy counts below remain preserved; the new comparison is reported separately under [What changed after completing the judge panel](#what-changed-after-completing-the-judge-panel).

Two numbers from the original r4 panel frame the case analysis:

- **Passing answers still contained errors.** 10 of the 53 passing answers contained at least one wrong material claim (lenient panel rule). Under the strict rule it was 20 of 52. Under the lenient rule, none of those errors was in the structured numbers. Every one was in a conclusion, a claim, a driver explanation or the memo.
- **Unsupported certainty was the most common label.** Judges tagged at least one claim as fabrication or unsupported certainty (taxonomy code E14) in 19 of 72 answers under the lenient rule and 32 of 72 under the strict rule.

The rest of this report describes five recurring patterns, with real cases and, where possible, an agent that handled the same task correctly. Each pattern ends with what a human reviewer should check.

## How to read this report

- **Data:** the original scorer r4 final records for all 72 scored answers: four products × nine tasks × two runs (see [`results/REPORT.md`](results/REPORT.md)). These remain the source for the case map and taxonomy counts; the shared-panel comparison is a separate result.
- **Labels:** each wrong claim carries one or more taxonomy codes (E01–E17) assigned by AI judges from other vendors. Codes overlap, so counts across codes cannot be added.
- **Two rules:** where the two judges disagreed, counts are given as lenient | strict. Antigravity answers had three judges and use a majority vote under both rules.
- **Quotes:** quotations come from the agents' saved answers. Numbers that would reveal the answer key are left out.
- **Product names:** they appear so that readers can see how the patterns are distributed. With 18 answers per product, these are case observations, not product ratings.

## 1. A complete analysis of the wrong population

**Task:** Q07 asks for a weekly gross-bookings extract for one server, S08.

**What happened:** three of the eight Q07 answers did the cleaning work well and then delivered totals for every server:
- **Grok Build:** both runs.
- **Claude Code:** one run.

**Why this error is hard to catch:**
- The SQL runs, the numbers reproduce exactly, and the deduplication and currency handling are sound.
- One Grok answer labelled its own metrics "All servers".
- The Claude memo explained the mismatch by "two data defects on server S08", and its table still covered every server.
- These agents understood the request and found the right issues, but the scope they had found did not carry through to the final deliverable.

**Handled correctly by:** Codex and Antigravity delivered S08 figures in all four of their runs.

**Reviewer check:** compare the final deliverable's population, time window, denominator and aggregation level with the request. "The code runs and the numbers reproduce" is not evidence that the right question was answered.

## 2. Calling an experiment invalid, then claiming its effect anyway

**Task:** Q17 asks whether a finished price test supports shipping offer B. The test's allocation does not match its design, and the two arms already differed before treatment.

**What happened (Antigravity):**
- **Diagnosis:** both runs identified the allocation problem correctly.
- **Re-estimation:** the agent then stratified and ran a regression.
- **Unsupported conclusion:** it reported the result as a real causal effect:
  - "regression adjustment confirming a negative treatment effect … (p < 0.0001)";
  - offer B "actually causes a 37.1% monetization loss among historical payers".

A milder version appeared in one Claude Code run, whose memo stated as fact that the cheaper offer "raised conversion".

**Handled correctly by:** Codex and Grok Build passed all four of their Q17 runs. They declined to ship on this evidence without claiming to know the true effect.

**Why it matters:**
- Holding the launch is a defensible decision; the error is the reason given for it.
- Regression adjustment and a small p-value do not restore a broken randomization.
- These agents knew the right vocabulary and found the problem, but the finding did not constrain the conclusion they wrote next.

**Reviewer check:** after an agent flags a validity problem, read every later sentence that states an effect, a loss or a lift. Each one should be reframed as descriptive or dropped.

## 3. A story built from behavioral records

**What the data contains:** payments, refunds with a generic reason code, logins and client versions. It has no support tickets, no crash logs, no inventory-consumption records and no satisfaction data.

**Q26:** asks why one customer requested a large refund. The data cannot answer this. Both Antigravity runs supplied a full narrative anyway:
- an "accidental bulk purchase";
- "customer support processed a partial refund" for the unconsumed portion;
- "Customer support's handling successfully retained a high-value customer through a fair, partial-refund compromise."

**The mirror-image error:** the requester asked whether the customer disliked the event rewards. Several answers (both Antigravity runs and one Grok Build run) ruled that out with certainty. The data cannot support "it was not X" any more than "it was Y".

**Q12:** asks what changed on S04 and what to investigate first. Antigravity answers stated things outside the warehouse as findings:
- "Engineering must audit the crash logs and network failures …";
- "Canary health monitoring failed to trigger automated rollbacks";
- the issue "is already resolved in production".

**Handled correctly by:** Codex and Claude Code passed all four of their Q26 runs. They reported what the records show and stated that the records cannot identify the customer's motive.

**Reviewer check:** for each explanation of *why*, ask which table it came from. Observed behavior can suggest a hypothesis. It is not evidence of a motive, of a support interaction, or of whether a production system is healthy.

## 4. Historical averages turned into a budget forecast

**Task:** Q16 asks which channel comparison should guide a budget discussion. The descriptive analysis is mechanical, and every product got the core comparison right in at least one run. The answers differed in what they claimed the numbers mean for future spend.

**Overclaim (Antigravity, run 2):** budget shifted on the pooled numbers would destroy a fixed number of cents "of cash return per dollar reallocated across every territory".

**Bounded claims (other products, same numbers):**
- **Claude Code:** the gain holds only "provided B can scale in that country without CPI or quality degradation".
- **Codex:** "a controlled incremental budget test, not a proven causal winner or a guaranteed scalable return".

**Why it matters:**
- Historical average return on ad spend says nothing about marginal cost, saturation or incrementality.
- A specific, confident budget forecast reads as actionable, which makes this one of the more costly errors in practice.
- The same Antigravity run passed the task, so the error sits entirely in the recommendation.

**Reviewer check:** when an answer moves from "A performed better than B" to "moving money to A will return X", look for evidence about the margin: a test, a lift study or a saturation curve. Without it, the forecast is an assumption.

## 5. A correct headline with unsupported extras

Some answers got the requested numbers exactly right and then added claims nobody asked for and nothing supports:

- **Q03:** asks for one week's gross bookings, refunds and net bookings "for finance". An Antigravity answer scored 100 on the numbers, then told finance it could record the amount "without reserving against Week 8 chargebacks or refunds". This is a forward-looking accounting judgement the data cannot make.
- **Q07:** says the weekly numbers "don't reconcile with finance". No finance ledger is provided. Antigravity's two passing answers claimed:
  - the extract was "fully resolving the discrepancy with finance";
  - the variance was "fully traced and resolved to the exact cent";
  - the extract "ensures automated parity between operational reporting and financial ledgers".

**Generic caveats did not offset these.** The silent-error measure (S) counts a wrong claim as warned only when a specific warning addresses that claim's limitation:
- Antigravity had 15 answers with a wrong material claim, and 14 of them had at least one unwarned wrong claim.
- In Q07, a caveat about one-cent rounding was offered against a wrong-server error. After audit it was rejected as a qualification for that error (scorer r4).

**Reviewer check:** read the memo as carefully as the numbers. A high task score says the requested figures are right. It says nothing about the advice that follows them.

## How the patterns fall across products

| Answers with at least one claim tagged… | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| E14 Fabrication or unsupported certainty | 0 \| 2 | 2 \| 8 | 2 \| 7 | 15 \| 15 |
| E17 Metric–decision mismatch | 0 \| 0 | 3 \| 4 | 1 \| 1 | 9 \| 9 |
| E12 Root-cause conflation | 0 \| 0 | 1 \| 2 | 1 \| 1 | 7 \| 7 |
| E08 Confounding or composition | 0 \| 1 | 3 \| 4 | 0 \| 0 | 5 \| 5 |
| Any wrong material claim (E) | 0 \| 2 | 6 \| 12 | 5 \| 9 | 15 \| 15 |
| Any unwarned wrong claim (S) | 0 \| 2 | 2 \| 11 | 4 \| 9 | 14 \| 14 |

All counts are out of 18 answers, shown as lenient | strict.

- **Antigravity:** its overclaiming in narrative and causal statements is the most pronounced, and it drives much of the overall E14 count.
- **Claude Code:** its weak points were scope drift (Q07) and an interpretation question on Q14 (see Limitations). Some supporting explanations were also stronger than the evidence. The wide gap between its lenient and strict counts means its judges often disagreed about these secondary claims.
- **Grok Build:** it sometimes found the data problems but did not deliver the requested scope (Q07). It also had one timeout.
- **Codex:** it delivered consistently in this pilot. The original strict rule flags supporting statements in two answers; the shared panel does not confirm silent errors in them. Neither result proves that it is error-free.

## The evaluator made pattern 1 too

The automatic scorer made the same kind of error as the agents. Before the r4 correction, its metric matcher compared numbers that had the right shape but the wrong identity, for example:
- an account median against a mean;
- active users against all assigned users;
- a later small purchase against the original refunded payment.

As a result, correct supplementary numbers were marked as errors. The audit found and fixed this in r4, and all 72 answers were regraded (see [`METHODOLOGY.md`](METHODOLOGY.md)). The lesson applies to automated review in general: checking that a number matches is only meaningful after checking that it measures the same population, statistic, event and time window.

## What changed after completing the judge panel

The original leave-own-provider-out design gave products different judges. If one judge interpreted warnings or supporting claims more strictly, excluding that judge from one product could change the apparent error rate. We therefore added 54 author-blinded reviews of the preserved answers. All 72 now have GPT, Claude and Grok reviews, including the author's own provider where applicable, for 216 reviews in total. This is a post-results robustness check; no contestant was rerun.

| Product | Original r4 mean (lenient / strict) | Shared-panel mean | Shared-panel core accuracy | Shared-panel silent errors |
|---|---:|---:|---:|---:|
| Codex | 100.00 / 97.89 | 99.60 | 14/14 | 0/18 (0.0%) |
| Claude Code | 83.73 / 82.76 | 83.73 | 10/14 | 5/18 (27.8%) |
| Grok Build | 81.82 / 79.74 | 81.82 | 9/14 | 6/18 (33.3%) |
| Antigravity | 83.00 / 83.00 | 83.00 | 7/14 | 14/18 (77.8%) |

Majority decisions and median component points preserve both orderings: Codex, Claude Code, Antigravity, Grok Build by mean score; Codex, Claude Code, Grok Build, Antigravity by core accuracy. Codex's small decrease from the old lenient mean comes from omitted explicit difference-in-differences quantities in its two Q12 answers. We did not observe a large Codex score decrease after adding GPT under this rule. That addresses the specific unequal-assignment concern without proving the judges are unbiased.

The larger change is methodological. Claude Code's original silent-error count ranged from 2/18 to 11/18 depending on the rule; it is 5/18 with the shared panel. Grok Build moves from 4/18 / 9/18 to 6/18. The agents wrote exactly the same answers. The evaluator's selection of wrong claims and interpretation of warnings changed the reported incidence. Silent-error rates should therefore always be accompanied by the judge assignment and combination rule.

Judges also made factual mistakes. A new review called a module missing because evidence files had neutral aliases; the original archive contains the module. An earlier review called supplementary figures wrong because they were absent from the reference calculation, but an independent calculation confirmed their rounded values. These cases show why disagreement requires evidence review, and why strictness alone is not a measure of judge quality. Original votes were retained.

Five statements across four answers still have exact three-way splits. The declared fallback variants agree on the means, core accuracy and silent-error counts in this table. Codex's wrong-material-claim count is 0/18 or 1/18; the disputed claim is qualified, so its silent-error count is 0/18 under either fallback. This means no silent error was confirmed by this panel rule, not that all Codex statements were independently proved correct. No independent human adjudication has resolved these statements.

The main practical finding survives: getting the calculation right and detecting a data defect do not guarantee a supported explanation or recommendation. The new finding is that the evaluator needs the same care with evidence boundaries as the agent. The [results report](results/REPORT.md#what-changed-with-the-same-judges-for-every-product) and [aggregate comparison](results/pilot1_shared_panel_comparison.json) retain the before/after figures. The taxonomy counts and interactive case map above have not been recomputed as shared-panel labels.

## What this means for using AI analysts

Arithmetic and code checks can be automated, and the agents rarely failed them. The judgement that needs a human is narrower and more specific:

1. **Ambiguous business questions:** confirm the population, time window and level of aggregation the requester actually meant.
2. **Explanations after a validity problem:** once the agent flags a broken experiment or confounding, every later effect claim is suspect.
3. **Root causes and motives:** each "why" needs a source table, or it should be labelled as a hypothesis.
4. **Budget and launch recommendations:** forward-looking claims need evidence about the margin, not only historical averages.
5. **The memo:** wrong claims in passing answers were concentrated in the prose. Caveats should name the specific claim they qualify.

## Limitations

- **Scale:** nine tasks on one synthetic dataset, two runs per product. The patterns describe the workflow; they do not explain model internals or training, and the per-product differences are not statistical estimates.
- **Judging:** labels come from AI judges, who disagreed materially on 41 of 72 original panels, and from a documented post-results audit (r4). That disagreement count is not a rate for the completed three-judge panel. The lenient | strict ranges show rule sensitivity, not confidence intervals. Later backfill reviews reuse the archived prompts and named models, but their dates and observed CLI versions differ. Explicit author masking cannot eliminate every style clue, and same-provider preference can remain.
- **Q14 ambiguity:** the Q14 request does not say whether "week 6" means calendar-week revenue or the week-6 registration cohort. A cohort reading is defensible, and both the wording and the scoring of that task should be improved before reuse.
- **Human detection:** this pilot did not test whether people would notice these errors. That remains open.
- **Who built it:** Claude Opus 5.5 implemented the benchmark and GPT-6.1-sol audited it; these are also the models behind Claude Code and Codex. The case analysis was drafted with the same models. See [How this project was built](README.md#how-this-project-was-built).
- **Reuse:** publishing these cases reveals part of what the nine Pilot-1 tasks test. Anyone running these tasks should turn off the agent's web search and URL fetching, and ideally allow network access only to the model's inference endpoint. Scores from such runs are a fresh run on known tasks, not a continuation of Pilot-1, and future official rounds should use new tasks.
