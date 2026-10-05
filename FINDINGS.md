# Where AI analyst agents go wrong: error patterns from Pilot-1

**The main finding:** the agents in this pilot were good at *finding* problems in the data. Finding a problem did not reliably stop them from overstating what the data could support. Most serious errors were not wrong arithmetic. They were conclusions that went past the evidence: a correct analysis of the wrong population, a causal effect claimed from an experiment the agent had just called invalid, a customer's motive invented from a payment log, or a budget forecast read off historical averages.

An interactive version of this report is in [`docs/findings.html`](docs/findings.html).

Two numbers frame the rest of this report:

- **Passing answers still contained errors.** 10 of the 53 passing answers contained at least one wrong material claim (lenient panel rule). Under the strict rule it was 20 of 52. Under the lenient rule, none of those errors was in the structured numbers. Every one was in a conclusion, a claim, a driver explanation or the memo.
- **Unsupported certainty was the most common label.** Judges tagged at least one claim as fabrication or unsupported certainty (taxonomy code E14) in 19 of 72 answers under the lenient rule and 32 of 72 under the strict rule.

The rest of this report describes five recurring patterns, with real cases and, where possible, an agent that handled the same task correctly. Each pattern ends with what a human reviewer should check.

## How to read this report

- **Data:** the scorer r4 final records for all 72 scored answers: four products × nine tasks × two runs (see [`results/REPORT.md`](results/REPORT.md)).
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
- **Codex:** it delivered consistently in this pilot. Even so, the strict rule flags supporting statements in two answers, so these results do not show that it is error-free.

## The evaluator made pattern 1 too

The automatic scorer made the same kind of error as the agents. Before the r4 correction, its metric matcher compared numbers that had the right shape but the wrong identity, for example:
- an account median against a mean;
- active users against all assigned users;
- a later small purchase against the original refunded payment.

As a result, correct supplementary numbers were marked as errors. The audit found and fixed this in r4, and all 72 answers were regraded (see [`METHODOLOGY.md`](METHODOLOGY.md)). The lesson applies to automated review in general: checking that a number matches is only meaningful after checking that it measures the same population, statistic, event and time window.

## What this means for using AI analysts

Arithmetic and code checks can be automated, and the agents rarely failed them. The judgement that needs a human is narrower and more specific:

1. **Ambiguous business questions:** confirm the population, time window and level of aggregation the requester actually meant.
2. **Explanations after a validity problem:** once the agent flags a broken experiment or confounding, every later effect claim is suspect.
3. **Root causes and motives:** each "why" needs a source table, or it should be labelled as a hypothesis.
4. **Budget and launch recommendations:** forward-looking claims need evidence about the margin, not only historical averages.
5. **The memo:** wrong claims in passing answers were concentrated in the prose. Caveats should name the specific claim they qualify.

## Limitations

- **Scale:** nine tasks on one synthetic dataset, two runs per product. The patterns describe the workflow; they do not explain model internals or training, and the per-product differences are not statistical estimates.
- **Judging:** labels come from AI judges, who disagreed materially on 41 of 72 original panels, and from a documented post-results audit (r4). The lenient | strict ranges show how sensitive the counts are to the combination rule. They are not confidence intervals.
- **Q14 ambiguity:** the Q14 request does not say whether "week 6" means calendar-week revenue or the week-6 registration cohort. A cohort reading is defensible, and both the wording and the scoring of that task should be improved before reuse.
- **Human detection:** this pilot did not test whether people would notice these errors. That remains open.
- **Reuse:** publishing these cases reveals part of what the nine Pilot-1 tasks test. Anyone running these tasks should turn off the agent's web search and URL fetching, and ideally allow network access only to the model's inference endpoint. Scores from such runs are a fresh run on known tasks, not a continuation of Pilot-1, and future official rounds should use new tasks.
