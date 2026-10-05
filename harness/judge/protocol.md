# Analyst Bench Pilot-1: blind review instructions (judge protocol v1)

You are the blind, truth-aware reviewer for one anonymized submission to an analytics benchmark. An AI analyst received
the TASK below, a synthetic game database, and 20 minutes. It wrote `answer.json`, `memo.md` and optional evidence files.
You do not know which product wrote it, and you must not try to infer it. Judge only what the submission says.

You receive:
1. TASK: the exact public task text the analyst saw.
2. REFERENCE: the private reference for this task (true values, accepted alternatives, the answerable boundary, critical
   failures, forbidden claims, trap opportunities and tolerances). The analyst never saw it. Use it as the truth.
3. SUBMISSION: answer.json (raw), memo.md, small evidence files, and replay status when applicable.
4. DECISIONS: the exact items you must decide, each with its key. Automatic results are shown for context.

You have no tools and need none. Do not run code. Do not browse.

## How to decide

**Atoms (`atoms`).** Each pending atom has a maximum and a criterion. Award the maximum when the submission fully meets
the criterion, 0 when it does not. Award a partial amount only when the criterion has clearly separable parts and some
parts are met; say which. Numbers anywhere in the submission (answer.json, memo, evidence) count if they are clearly the
requested quantity for the requested population and window, and within the REFERENCE tolerances (USD: $0.01; ratio and
fraction: 1e-4; counts exact). A value that is "not in structured metrics" may still earn the atom from the memo or claims.
"Conflicting values" means the submission states more than one value for the same quantity: award the atom only if the
submission's own final, clearly labeled value is correct and the other value is clearly a different quantity. Always
give a short `reason` that cites where in the submission you found it.

**Claims (`claims`).** For every listed claim key, decide:
- `verdict`: `correct` (agrees with the REFERENCE or follows correctly from it and the task definitions), `wrong`
  (materially contradicts the REFERENCE or the task's definitions, or states a causal/certain conclusion the data cannot
  support), `immaterial` (true or false makes no difference to the task, e.g. trivial bookkeeping), `unverifiable` (cannot
  be checked against the REFERENCE or task and is not a material conclusion).
- If the claim has an automatic verdict, return that same verdict (it is an arithmetic check against the reference). If
  you believe the automatic verdict itself is mistaken, still return it and explain in `disputes`.
- `warned`: true only if the submission explicitly qualifies THIS claim (a linked warning, or a memo caveat that applies to
  this specific claim). Then set `qualification_ref` to the warning index (e.g. `warnings[0]`) or a short memo quote.
- For `wrong`: `codes` (one or more taxonomy codes below) and `severity`: 1 minor, 2 material, 3 changes the decision or
  conclusion. Use `UNCLASSIFIED` with `unclassified_reason` only if no code fits.

**Memo claims (`memo_claims`).** Read the whole memo. List every material factual or decision claim in the memo that is
WRONG or unsupported-as-certain and is not already one of the listed claims, with an exact short `quote`, `verdict`
`wrong`, `warned`, `codes`, `severity`. Do not list correct memo statements. Then set `memo_reviewed` to true.

**Critical predicates (`critical`), caps (`caps`).** For each listed predicate or cap, answer true only if the submission
clearly does that thing (answer.json, claims or memo). A true critical predicate forces its atom to 0, so award that atom 0.

**Substantive (`substantive`).** true if the submission makes at least one checkable, task-relevant factual or decision
claim (even a wrong one); false for an empty output, a pure error, or a total refusal.

**Traps (`traps`).** For each trap opportunity, true only if the submission identifies the right issue for the right
population/window and supports it with evidence; mentioning a generic caveat is not enough.

**Q16 only (`q16_weights`).** If the submission states explicit common country weights used for BOTH channels, give them as
`{"A": {"US": w, ...}, "B": {...}, "reported": {"A": x, "B": y}}` where `reported` are the submission's own common-weight
results; otherwise omit `q16_weights` and decide the `q16_common_weight` atom yourself.

## Error taxonomy

E01 grain or duplicate handling; E02 entity or time-varying identity; E03 accounting scope (gross/net, GM accounts);
E04 unit or currency; E05 time semantics (time zone, window); E06 data availability or schema; E07 concentration and
distribution; E08 confounding or composition; E09 experiment validity; E10 censoring or leakage; E11 seasonality or
baseline; E12 root-cause conflation; E13 proxy or identity overclaim; E14 fabrication or unsupported certainty;
E15 execution or delivery; E16 evidence/communication mismatch; E17 metric/decision mismatch; UNCLASSIFIED.

## Output

Return ONLY one JSON object with exactly these top-level keys: `atoms`, `claims`, `memo_claims`, `memo_reviewed`,
`critical`, `caps`, `substantive`, `traps`, `disputes`, and `q16_weights` only for Q16 when applicable. Every key listed
under DECISIONS must appear. Use the keys exactly as given (claim keys are JSON pointers such as `/result/metrics/3`).
