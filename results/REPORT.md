# Pilot-1 results — scorer r4 correction

**Status:** All 72 preserved submissions have been regraded. No contestant was rerun and no new judging call was made. This is an explicitly post-results evaluator correction, authorized October 5, 2026. Original r3 scores, judgments and outputs remain preserved as superseded history.

Nine tasks × two repetitions × four products used the same frozen synthetic warehouse and 1,200-second limit. The original cross-vendor panel supplied 162 judgments: two eligible judges for Codex, Claude Code and Grok Build; three for Antigravity. Two-judge results are shown as lenient | strict. Antigravity uses majority and median points in both versions. These are rule sensitivities, not confidence intervals.

## Current metrics

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

## Scores by task

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

This is one synthetic dataset and only 18 attempts per product. It does not establish broad product superiority or measure whether humans detect errors. The qualitative judgments remain those of the original AI panel, with the documented corrections; no new independent human adjudication was performed.

Collection used personal subscription allowances and a shared macOS sandbox rather than a VM. The mid-wave quota gate change, same-day wave-1 repetitions, stale-driver incident and shared Claude allowance remain disclosed in the operations report. Antigravity additionally allowed localhost for its language server, and its server-side web search could not be disabled; it made zero searches in the selected runs. Grok had seen references earlier as a wave-1 judge. Review moved from planned owner review to AI judging and then a cross-vendor panel after collection. ISO parsing and the secondary speed bonus were also changed during the pilot. r4 was decided after all results were visible, and that timing is explicit.

The public release withholds the data, generator, answer key, task-specific scorer, and raw submissions/judgments. It is a results/methods release and cannot reproduce this scoring end to end.
