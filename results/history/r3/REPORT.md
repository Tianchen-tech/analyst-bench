# Pilot-1 results: four products (LLM judge panel)

**Scope:**
- **Design:** 9 tasks × 2 repetitions per product, on one synthetic dataset, with a 1,200 s cap and the same frozen tasks, data and controller boundary for all products.
- **Wave 1:** Codex (`gpt-6.1-sol`, high) and Claude Code (`claude-opus-5-5`, high).
- **Wave 2:** Grok Build (`grok-4.7`, high) and Antigravity CLI (`gemini-3.8-flash-high`).
- **Scoring:** scorer r3. Reviews come from a leave-own-provider-out judge panel (ID-50):
  - judges: GPT (Codex CLI), Claude (Claude Code) and Grok (Grok Build); 162 judgments in total;
  - each packet is judged by the judges whose provider is not the author's: two judges for Codex, Claude Code and Grok Build, three for Antigravity.
- **Disagreements** (ID-55) are reported as a **lenient** and a **strict** version:
  - lenient: either judge's benefit of the doubt counts;
  - strict: either judge's objection counts;
  - Antigravity is decided by majority in both versions.
- **Data:** `private/results/pilot1_four_products.json`.

This is a pilot. Each product has 18 attempts, so differences are descriptive, not statistically established.

## Headline (lenient | strict)

| Metric | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| Core accuracy (7 tasks × 2) | **14/14 \| 14/14** | 10/14 \| 10/14 | 9/14 \| 8/14 | 7/14 \| 7/14 |
| Valid abstention (Q26, Q27) | 4/4 | 4/4 | 3/4 | 2/4 |
| Trap recall | 22/22 \| 21/22 | 19/22 | 20/22 | 18/22 |
| Attempts with a wrong material claim (E) | 2 \| 4 /18 | 7 \| 13 /18 | 7 \| 10 /18 | 15 /18 |
| Silent errors (wrong and unwarned, S) | 2 \| 4 /18 | 3 \| 11 /18 | 4 \| 9 /18 | 14 /18 |
| Mean score | 100.0 \| 97.9 | 83.7 \| 82.8 | 79.0 \| 76.9 | 81.6 |
| Speed-adjusted mean (ID-54, +10% max) | 106.9 \| 104.7 | 90.7 \| 89.7 | 81.5 \| 79.3 | 85.5 |
| Median time per attempt | 331 s | **116 s** | 849 s | 275 s |
| Correct answers per agent hour | 9.8 | **23.4** | 3.1 \| 2.8 | 6.6 |
| Same success in both repetitions | 9/9 | 7/9 | 7/9 \| 6/9 | 8/9 |
| Timeouts / format failures | 0 / 0 | 0 / 0 | 1 / 0 | 0 / 0 |

**Reading:**
- **Codex** is the most accurate and the most consistent: every core task succeeded in both repetitions under both versions.
- **Claude Code** is the fastest by far, about 3× Codex's speed, and has the most correct answers per hour. Its failures concentrate in Q14 (both repetitions) and in one repetition each of Q07 and Q16.
- **Grok Build** is the slowest: its median is 14 minutes, and one attempt hit the 20-minute cap.
- **Antigravity** has the highest error and silent-error incidence (15/18 attempts contain a wrong material claim), and it lost both repetitions of Q26.
- **Robustness:** the ordering Codex > Claude Code > Grok Build ≈ Antigravity on core accuracy holds in both versions.

## Per task (lenient score; ✓/✗ success)

| Task | Codex | Claude Code | Grok Build | Antigravity |
|---|---|---|---|---|
| Q03 | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ |
| Q04 | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ |
| Q07 | 100 ✓, 100 ✓ | 100 ✓, 0 ✗ | 40 ✗, 0 ✗ | 100 ✓, 100 ✓ |
| Q12 | 100 ✓, 100 ✓ | 92.9 ✓, 89.3 ✓ | 88.1 ✓, 93.0 ✓ (timeout) | 74.7 ✗, 74.7 ✗ |
| Q14 | 100 ✓, 100 ✓ | 25 ✗, 25 ✗ | 50 ✗, 50 ✗ | 25 ✗, 75 ✗ |
| Q16 | 100 ✓, 100 ✓ | 100 ✓, 75 ✗ | 100 ✓, 100 ✓ | 90 ✓, 75 ✗ |
| Q17 | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 75 ✗ | 77.5 ✗, 77 ✗ |
| Q26 | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 50 ✗, 75 ✓ | 50 ✗, 50 ✗ |
| Q27 | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ | 100 ✓, 100 ✓ |

## Open policy point (not changed after results)

**What happened:** Grok Build's Q12 r2 hit the 1,200 s cap. The scorer graded the files present at the cap, and the attempt scored 93.0 (lenient) or 89.3 (strict), so it counts as a success.

**Why it is open:** design 5.4's core-accuracy row says "terminal failures count unsuccessful". The frozen aggregate counts success from the score alone and lists timeouts separately.

**Effect under the design wording:** Grok Build's core accuracy would be 8/14 lenient and 7/14 strict. Nothing else changes. This is disclosed rather than changed after the results were seen.

## Disclosures (all recorded in the design log)

1. **Isolation:** host sandbox, not a VM (ID-44).
2. **Wave-1 conditions:**
   - the same-day repetitions, the mid-wave change of the quota gates and the stale-driver incident (`WAVE1_REPORT.md`);
   - Claude Code's allowance was shared with the operator.
3. **Review protocol changed after collection.** Owner review was replaced by LLM judging because of the workload (ID-47), and then by the leave-own-provider-out panel (ID-50). The owner consented to sending blind packets and the private references to xAI, OpenAI, Anthropic and Google; training and memory were off where the account allows it. The wave-1 Grok-only review is superseded history.
4. **Scorer changes made after seeing wave-1 results:**
   - ID-48: a provided `task.md` cited as evidence is valid;
   - ID-51: ISO interval notation is read correctly; this restored 20 points on each Codex Q07 answer;
   - ID-54: the speed-adjusted score was defined during wave 2.
5. **Products:**
   - Gemini CLI was rejected by Google's personal-account policy, so Antigravity CLI is the Google product (ID-52).
   - Antigravity's sandbox also allowed localhost (for its language server), and its server-side web search could not be disabled (ID-53). It made **0** web searches in its 18 formal attempts.
   - Grok had seen the task references earlier as the wave-1 judge, with training and memory off.
6. **Judging:**
   - Two-judge disagreement is reported as a range (ID-55).
   - Material disagreements appeared in 38 of 72 packets. Mostly they concern whether a claim is wrong or warned; success differs in only 4 packets.
   - Automatic arithmetic verdicts were never overridden.
7. **Scale:** 9 tasks and one dataset. Results are per task and descriptive.
