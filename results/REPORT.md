# Pilot-1 results — r4 correction and shared-panel robustness check

**Status:** The r4 correction regraded all 72 preserved submissions without new contestant or judge calls. A subsequent, separate comparison added 54 blind reviews to give every answer the same three judges. Both changes followed inspection of the results on October 5, 2026. Original r3 history and original r4 results remain preserved.

Nine tasks × two repetitions × four products used the same frozen synthetic warehouse and 1,200-second limit. The original cross-vendor panel supplied 162 judgments: two eligible judges for Codex, Claude Code and Grok Build; three for Antigravity. Two-judge results are shown as lenient | strict. Antigravity uses majority and median points in both versions. These are rule sensitivities, not confidence intervals.

## What changed with the same judges for every product

The original panel excluded a product's own provider. That gave Codex, Claude Code and Grok Build different pairs of judges, while Antigravity had all three. Differences in judge strictness could therefore affect the product comparison. After seeing this concern, we added 54 author-blinded reviews: every preserved answer now has one GPT, one Claude and one Grok review, including its own provider where applicable. The original 162 reviews and r4 results remain preserved. No contestant was rerun.

This separate robustness check applies majority decisions and median component points to all four products. It reuses the archived initial prompts and the named models, with the same r4 identity corrections. Collection happened later; dates, observed CLI versions and model identifiers are recorded. It is not a pre-registered primary result or an independent human assessment.

| Product | Original r4 mean (lenient / strict) | Shared-panel mean | Shared-panel core accuracy | Original r4 silent errors (lenient / strict) | Shared-panel silent errors |
|---|---:|---:|---:|---:|---:|
| Codex | 100.00 / 97.89 | 99.60 | 14/14 | 0/18 / 2/18 | 0/18 (0.0%) |
| Claude Code | 83.73 / 82.76 | 83.73 | 10/14 | 2/18 / 11/18 | 5/18 (27.8%) |
| Grok Build | 81.82 / 79.74 | 81.82 | 9/14 | 4/18 / 9/18 | 6/18 (33.3%) |
| Antigravity | 83.00 / 83.00 | 83.00 | 7/14 | 14/18 / 14/18 | 14/18 (77.8%) |

**The performance ordering is stable in this pilot.** Mean scores still order Codex, Claude Code, Antigravity, then Grok Build; core accuracy orders Codex, Claude Code, Grok Build, then Antigravity. Codex stays at 14/14 core successes. Its shared-panel mean is 99.60, compared with the original 100.00 / 97.89. The small decrease from the old lenient mean comes from both Q12 answers omitting an explicit difference-in-differences quantity required by the rubric. Adding GPT did not produce a large Codex score decrease under the declared combination rule.

**Silent-error incidence depends materially on the evaluator.** Claude Code's original 2/18 / 11/18 becomes 5/18; Grok Build's 4/18 / 9/18 becomes 6/18. These are changed judgments of the same saved answers, not changes in agent ability. All 18 answers per product are substantive, so the denominator is 18. A correct headline number can still coexist with a wrong or insufficiently qualified explanation in the memo.

**A stricter judge is not automatically a more accurate judge.** Audit checks found evaluator mistakes as well as agent mistakes. A new missing-module objection arose because neutral review aliases renamed the evidence files while leaving an import unchanged; the original archive contains the dependency. This invalidates that objection's missing-file reason, but does not by itself prove complete script reproducibility. Another numerical objection confused absence from the reference calculation with factual error; an independent calculation confirmed the submitted rounded figures. Source votes remain preserved.

The shared panel addresses unequal judge assignment; it does not demonstrate unbiased grading. Same-provider preference, incomplete references and presentation effects can remain. There are five exact three-way claim splits across four answers. Their existing lenient/strict fallbacks agree on the means, core accuracy and silent-error counts above, but Codex's wrong-material-claim count is 0/18 or 1/18. That disputed statement is qualified, so its silent-error count remains 0/18 under either fallback. Zero panel-confirmed silent errors is not proof of zero true errors. No independent human adjudication has resolved these statements.

The main error-pattern conclusion still stands: review the deliverable's scope, causal interpretation, customer-motive claims and memo, even when the requested calculations pass. The added methodological finding is that evaluator assignment and warning interpretation must be reported alongside silent-error rates. The error-taxonomy counts elsewhere remain the original r4 counts; they have not been relabelled as shared-panel results.

The aggregate comparison is inspectable in [`pilot1_shared_panel_comparison.json`](pilot1_shared_panel_comparison.json). The old two-judge lenient/strict endpoints and the exact-three-way fallbacks are rule sensitivities, not confidence intervals.

## Original r4 metrics (preserved baseline)

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

All 18 selected responses per product are substantive. Silent-error rates therefore use denominator 18 here; an empty response would not silently become an error-free substantive answer. The excluded Claude quota interruption remains documented as infrastructure, with its selected replacement.

## Original r4 scores by task

| Task | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| Q03 | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ |
| Q04 | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ |
| Q07 | 100.0 ✓, 100.0 ✓ \| 100.0 ✓, 80.0 ✓ | 100.0 ✓, 0.0 ✗ | 40.0 ✗, 26.7 ✗ \| 33.3 ✗, 26.7 ✗ | 100.0 ✓, 100.0 ✓ |
| Q12 | 100.0 ✓, 100.0 ✓ \| 96.0 ✓, 96.0 ✓ | 92.9 ✓, 89.3 ✓ | 88.1 ✓, 93.0 ✗ (timeout) \| 86.0 ✓, 89.3 ✗ (timeout) | 74.7 ✗, 74.7 ✗ |
| Q14 | 100.0 ✓, 100.0 ✓ | 25.0 ✗, 25.0 ✗ \| 25.0 ✗, 12.5 ✗ | 50.0 ✗, 50.0 ✗ | 50.0 ✗, 75.0 ✗ |
| Q16 | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 75.0 ✗ | 100.0 ✓, 100.0 ✓ \| 100.0 ✓, 75.0 ✗ | 90.0 ✓, 75.0 ✗ |
| Q17 | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 77.5 ✗, 77.0 ✗ |
| Q26 | 100.0 ✓, 100.0 ✓ \| 95.0 ✓, 95.0 ✓ | 100.0 ✓, 100.0 ✓ \| 95.0 ✓, 100.0 ✓ | 50.0 ✗, 75.0 ✓ | 50.0 ✗, 50.0 ✗ |
| Q27 | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ | 100.0 ✓, 100.0 ✓ |

## What r4 corrects

- The metric matcher checks statistic, population, weighting, event identity and calendar/cohort windows. The all-output regression covers 1,358 metrics. Forty-nine formerly matched identities are corrected, including 26 all-company metrics and three cohort concentration metrics. An unsupported supplementary quantity is sent to review; it is not compared to an unrelated reference or automatically called correct.
- Semantic objections survive normalization and finalization. An unresolved objection blocks final scoring; a versioned resolution binds its exact source notes and policy. Original judgments are unchanged. Derived judgments identify every edited decision and its source hashes.
- Memo warnings follow the same two-judge any/all rule as structured claims. A three-judge memo warning needs an affirmative majority of the entire eligible panel. Rounding and gross/net caveats do not qualify an incorrect server scope.
- Newly exposed review items receive explicit evidence decisions. These audit derivations are AI repair decisions, not new blind judgments or human review. Other qualitative panel decisions are carried forward with their limitations.
- Timeouts/errors are unsuccessful deliveries under the pre-registered design. A saved answer keeps its content score and E/S labels. The timeout affects accuracy, throughput, repetition agreement and successful-time summaries consistently.

The corrected disagreement counter finds **41/72** original saved panels with a material disagreement (r3 reported 38/72). After applying the explicitly recorded r4 derivations, **40/72** derived panels disagree. The two figures use different decision versions and must not be conflated.

## Supported interpretation

Codex passed all seven core tasks in both repetitions under both rules. Removing evaluator-created errors changes its error profile; a passed task still need not have every supplementary claim accepted by every reviewer. Claude Code has the shortest median runtime and the highest successful deliveries per agent hour in this pilot. Grok Build has the longest median runtime and one timeout. Long runtime is not evidence of training failure, nor does this experiment identify a causal relationship between reasoning time and errors.

The diagnostic cases are more useful than a generalized ranking: the wrong delivery scope in Q07, confusion between a cohort window and a calendar window in Q14, causal recommendations despite an invalid experiment, and unsupported customer motives. The evaluator's own metric-identity mistakes are retained as regression evidence.

## Limitations and protocol disclosures

This is one synthetic dataset and only 18 attempts per product. It does not establish broad product superiority or measure whether humans detect errors. The preserved r4 baseline uses the original AI panel with documented corrections; the separate shared-panel comparison includes the 54 later reviews. Neither has new independent human adjudication. Backfill dates and CLI versions differ from the original collection, and masking explicit product labels cannot eliminate all author clues.

Collection used personal subscription allowances and a shared macOS sandbox rather than a VM. The mid-wave quota gate change, same-day wave-1 repetitions, stale-driver incident and shared Claude allowance remain disclosed in the operations report. Antigravity additionally allowed localhost for its language server, and its server-side web search could not be disabled; it made zero searches in the selected runs. Grok had seen references earlier as a wave-1 judge. Review moved from planned owner review to AI judging and then a cross-vendor panel after collection. ISO parsing and the secondary speed bonus were also changed during the pilot. r4 was decided after all results were visible, and that timing is explicit.

The public release withholds the data, generator, answer key, task-specific scorer, and raw submissions/judgments. It is a results/methods release and cannot reproduce this scoring end to end.
