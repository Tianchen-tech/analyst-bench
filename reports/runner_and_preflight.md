# Pilot-1 runners (step 7), first implementation (2026-10-03)

**Status (updated 2026-10-04 UTC):** the controller, egress proxy, sandbox profile and both adapters pass the real toy preflight on the bound runner. The run bundle is assembled and the build certifies **`EVALUATION_READY`**. Formal runs have not started.

## Decisions

- **ID-43:** reasoning effort high is confirmed by the owner (GPT 6.1 sol's default is light) as a declared, reported benchmark override for both products. The budget is subscription allowance only ($0 incremental).
- **ID-44 (confirmed by the owner, 2026-10-03):** isolation on the owner's Mac through a per-run host sandbox instead of a VM. Its known limits are listed in the design log and stay disclosed with the results.
- **ID-45:** run-bundle contract `pilot1-bundle-v2` binds the runner code to the preflight run records (see the section at the end).

## Products (`private/runners/products.json`)

| | Codex | Claude Code |
|---|---|---|
| Binary | bundled in ChatGPT.app, `codex-cli 0.160.0` (version command observed) | `@anthropic-ai/claude-code@2.1.289` (npm `latest`), pinned in `.tools/claude-code`, `2.1.289 (Claude Code)` |
| Adapter | `private/runners/adapters/codex_exec.py` (`ADAPTER_ID = "codex_exec"`) | `private/runners/adapters/claude_code_print.py` (`ADAPTER_ID = "claude_code_print"`) |
| Model / effort | `gpt-6.1-sol`, `model_reasoning_effort="high"` (identity to be observed at preflight) | `claude-opus-5-5`, `--effort high` (to be observed) |
| Auth | ChatGPT Plus: `auth.json` of a clean baseline profile (`.tools/profiles/codex`), copied into each run | Claude Pro: owner-created `claude setup-token` file (`.tools/profiles/claude/oauth_token`), passed as `CLAUDE_CODE_OAUTH_TOKEN`; never printed or recorded |
| Session | `exec --json --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check`, web search disabled; Codex's inner sandbox bypassed inside the external boundary | `-p --output-format stream-json`, `--permission-mode acceptEdits`, frozen tools Read/Write/Edit/Bash/Glob/Grep, WebSearch/WebFetch disallowed, no setting sources, strict MCP, no session persistence, non-essential traffic off |
| Egress allowlist (to be confirmed by the smoke run) | chatgpt.com, *.chatgpt.com, api.openai.com, auth.openai.com | api.anthropic.com, claude.ai, *.claude.ai, console.anthropic.com |

API-key variables are refused in a contestant environment.

## Controller (`private/runners/controller.py`)

- **Fresh run root:** work/ holds exactly `task.md` and a read-only database clone, with the listing and both hashes verified against the source. It also has a fresh home and tmp, and a per-run profile copy.
- **Canary:** a canary outside work/ is placed before every run, and a sandboxed probe must fail to read it or list the private repository.
- **Sandbox:** sandbox-exec, with file contents readable only from system locations, the product install, `.tools/replay-env` plus the base Python (minus its site-packages), and the run root. Writes are allowed only in the run root. Network is allowed only to the controller's allowlist proxy, which tunnels HTTPS CONNECT to listed hosts on port 443 and denies and logs everything else.
- **Launch:** argument arrays only; the opening prompt (design 4.1, verbatim) is never interpolated by a shell. stdout (the product's JSON events) and stderr are written to files outside work/.
- **Deadline:** 1,200 s. Every descendant ever observed is tracked by `ps` polling. At the cap the whole tree is killed (TERM then KILL), and outputs are snapshotted only after the kill.
- **Run record (design 6.1 fields):** run/task/repetition, product, adapter, version command and executable SHA-256, the requested model and the models seen in the transcript, reasoning setting, selection source, settings snapshot hash, times, elapsed, stop reason, outcome, usage when exposed (Claude's API-equivalent cost is labelled as such), egress allowed/denied (the external-access attempts), output hashes, database and task unchanged, canary result, availability signals.
- **Availability:** a run with no answer and a quota, rate-limit, overload or auth-failure signal is `availability_limit`, an availability event under ID-43 and never an analysis error. The preflight stops the stage on it.

## Verification with a fake product (host, 7 tests)

**Fake run:** the staging listing is exact and the canary check passes. Reading the private repository, `~/.codex`, `~/.claude`, the home listing or the run canary, writing outside work/, writing the database, and opening a direct network connection all fail with `PermissionError` from the sandbox. A request to example.com through the proxy is refused, with `example.com:443` logged as denied. DuckDB in the common environment works. Usage and model are parsed from the transcript.

**Other tests:**

- **Forced timeout:** a detached grandchild sleeping 600 s, under an 8 s cap, gives `timeout` with 0 processes left.
- **Proxy:** denies non-CONNECT requests and non-listed hosts.
- **Refusals:** reused output directories are refused.
- **Availability patterns:** they do not fire on a `logins` query.
- **Preflight plan:** eight distinct runs with alternating product order.

## Toy preflight (`private/runners/toy/build_toy.py`, `scripts/preflight.py`)

The toy database uses seed 7 with values unrelated to the benchmark. There are three toy tasks:

- **toy1**, numeric with a saved query; gold total $1,634.14, 59 payers;
- **toy2**, incomplete data; expected `not_identifiable`;
- **toy3**, invites fetching a URL; used only for the blocked-access check.

Stages:

- `check`: prerequisites only;
- `smoke`: one toy1 run per product, to observe identity, egress hosts and usage;
- `runs`: the eight runs (2 products × toy1/toy2 × 2 repetitions, alternating order, excluded from scoring);
- `checks`: per product, one forced timeout (30 s cap) and one blocked-access run.

Outputs go to `private/runs/preflight/…` (git-ignored, hash-recorded).

## Owner steps needed before the smoke run

1. Log Codex into the clean baseline profile.
2. Create the Claude subscription token file.

The exact commands are in the chat summary.

**Suite:** inside the agent sandbox 426 passed, 41 skipped. The proxy test binds a local port, which the agent sandbox forbids, so it is now host-only. On the host all 7 runner tests pass.

## Smoke runs (2026-10-03)

**Codex: confirmed.**

- **Identity:** the session evidence copied from the disposable home records model `gpt-6.1-sol` and effort `high`.
- **toy1:** answered correctly, with the query saved, in 71 s.
- **Usage:** recorded from `--json` (about 79k input, 55k cached, 1.8k output and 48 reasoning tokens).
- **Behaviour:** no web-search events; 0 agent external-access attempts; the canary passed; the database was unchanged.
- **Egress:** allowed hosts were `chatgpt.com` and `ab.chatgpt.com`. Codex's own background requests to `*.oaiusercontent.com` (17) are denied and recorded separately as `denied_product_background`, so they do not count as agent attempts.
- **Fix:** `--ephemeral` was dropped, because it suppressed the session file the controller uses to observe identity. The file lives only in the per-run home and is copied as hashed evidence.

**Claude Code: blocked on authentication.**

- **First attempt:** it failed because Claude Code opens `/tmp/claude-<uid>`. Fixed with `CLAUDE_CODE_TMPDIR` pointing to the run's own short temp directory; run roots now live at `/private/tmp/ab-…` to respect socket path limits. Allowing the shared `/tmp/claude-<uid>` was rejected, because it would expose other sessions.
- **Second attempt:** the model `claude-opus-5-5` was configured and `api.anthropic.com` was reached, but the API returned **401 authentication_failed**. The run was classified as `availability_limit` and the stage stopped, as designed.
- **Diagnosis:** a shape-only check of the token file, without reading it out, shows it does not hold a subscription token: no `sk-ant-oat` prefix, 92 characters with 6 internal spaces. The owner needs to recreate the file.

## Preflight results (2026-10-03, real products, toy tasks only, excluded from scoring)

**Claude Code smoke run** (after the token file was recreated through a no-clipboard-overwrite procedure; shape check only): `claude-opus-5-5` was confirmed from the init and usage events; toy1 was correct in about 28 s; egress went only to `api.anthropic.com`.

- **Effort:** the product reports `per_turn_effort_active: true` but does not echo the level; `--effort high` was passed.
- **Tools:** `--allowedTools` only pre-approves and does not restrict, so remote and scheduling tools (Cron*, RemoteTrigger, ScheduleWakeup, SendMessage) are now disallowed as a declared override. Native `Task` subagents remain.
- **Allowlists** narrowed to the hosts actually used: Claude `api.anthropic.com`; Codex `chatgpt.com`, `ab.chatgpt.com`, plus `auth.openai.com` for token refresh.
- **Quota telemetry** is recorded per run: Claude rate-limit events and Codex session `rate_limits`. Informational "allowed" events are not availability signals. Paid overage was reported as disabled on the Claude account (`overageStatus: rejected`) while the status was `allowed`. The `allowed_warning` events in later runs omit that field and report only `isUsingOverage: false`. The formal driver must stop on any `isUsingOverage: true` (ID-43: $0).

**The eight runs** (`private/runs/preflight/runs-*`; alternating order per block):

| Run | Outcome | Time | Model observed | Toy check |
|---|---|---:|---|---|
| Claude toy1 r1 | completed | 25 s | claude-opus-5-5 | total and payers correct; SQL saved |
| Codex toy1 r1 | completed | 59 s | gpt-6.1-sol (effort high) | correct; SQL saved |
| Codex toy2 r1 | completed | 73 s | gpt-6.1-sol | `not_identifiable` |
| Claude toy2 r1 | completed | 28 s | claude-opus-5-5 | `not_identifiable` |
| Codex toy1 r2 | completed | 68 s | gpt-6.1-sol | correct; SQL saved |
| Claude toy1 r2 | completed | 25 s | claude-opus-5-5 | correct; SQL saved |
| Claude toy2 r2 | completed | 30 s | claude-opus-5-5 | `not_identifiable` |
| Codex toy2 r2 | completed | 89 s | gpt-6.1-sol | `not_identifiable` |

In all eight runs the canary check passed, the database was unchanged and there were 0 agent external-access attempts. Codex's 17 background requests per run were denied and recorded apart.

Quota after the eight runs:

| Product | 5-hour window | Weekly window |
|---|---|---|
| Claude | 20% → 22% | 22% → 23% |
| Codex | 1% → 3% | 14% → 15% |

Toy runs are much lighter than the 20-minute formal tasks, so these figures are not a forecast for the formal wave.

**Adapter checks** (`private/runs/preflight/checks-*`):

- **First attempt:** Claude finished before a 30 s cap, so the timeout was not exercised, and it attempted no fetch, so blocking was not exercised either.
- **Fixes:** elapsed time is now measured at exit or deadline, before the kill routine. The forced-timeout cap is 8 s. toy3 explicitly asks for a command-line download; only its task.md text changed, and the toy databases are byte-identical to those the eight runs used.
- **Results after the fix:** both products were stopped at 8.00 s with 0 processes left. Both attempted `example.com`; the requests were denied and logged (Codex twice, Claude once), and each answered without the external data.

## Run bundle assembly (2026-10-03, ID-45)

- **Runner binding.** Each run record now carries `runner_binding`, the hashes of `controller.py`, `proxy.py`, `adapters/_common.py`, `products.json` and the product's adapter. Contract `pilot1-bundle-v2` reads every preflight run record back and requires these hashes and the recorded identity, model, staging, canary, times, stop reason and transcript to match the bundle. Six new attack tests cover it (41 gate tests pass).
- **The first real preflight cannot certify.** Its records predate the binding, and the adapters and controller were edited after its eight runs (between `b4a80aa` and `8a0a29b`). A dry assembly against it fails on exactly that (12 records: runner files or adapter differ) and on nothing else: policies, products, data freeze, gold, grader and policy binding, and the schedule all pass. It stays in `private/runs/preflight/` as history.
- **Repeat on committed runner `087af41`:** `preflight.py runs` and `preflight.py checks` must run on the host. The agent sandbox cannot apply sandbox-exec, and running outside it needs the owner.
- **Assembler:** `scripts/assemble_run_bundle.py` writes the policies, settings snapshots, $0 budget approvals (bound to the subscription-only decision note), the seeded 36-slot schedule and the preflight references, then runs the bundle check.
- **Pseudonym salt:** regenerated (32 bytes, mode 600, git-ignored; content never printed).

**Second real preflight, on runner `087af41`** (owner-run; `runs-20261004T031322Z`, `checks-20261004T032033Z`):
- **Eight runs:** all completed and correct (toy1 total, payers and saved SQL; toy2 `not_identifiable`). Canary passed, toy databases unchanged, no agent egress. Models observed: `gpt-6.1-sol` (effort high in the session) and `claude-opus-5-5`.
- **Checks:** both forced timeouts stopped at 8.00 s with 0 processes left. Both blocked-access runs were denied `example.com:443` twice.
- **Quota:** Claude 5-hour 40% to 42%, 7-day 25%, status `allowed_warning`. Codex 5-hour 6% to 8%, weekly 15%.
- **Assembly:** a bundle assembled from this preflight passed the full v2 check (bundle sha `86254e42…`).

**Defect found and fixed before formal runs.** Claude Code emits `rate_limit_event` with status `allowed_warning` once utilization passes a threshold. The availability classifier ignored only `allowed`, so it flagged these warnings as limit hits on all six Claude runs and checks. For a completed run that changes nothing. A formal Claude run that ended without output would have been labelled an availability event, which is eligible for replacement, instead of an incomplete run. That bias would apply only to Claude. Below-limit statuses (`allowed`, `allowed_warning`) are now parsed as telemetry and a `rejected` event is still caught (test added). On these transcripts the corrected classifier finds no signals.

Because `controller.py` changed, the second preflight no longer matches the runner binding: the assembler fails on exactly the 12 records and nothing else. It is kept as history, and the preflight must run a third time on the corrected runner.

**Third real preflight, on corrected runner `aac99af`** (owner-run; `runs-20261004T032850Z`, `checks-20261004T033544Z`):
- **Eight runs:** all completed and correct. Codex took 55–87 s; Claude 25–28 s. Canary passed, toy databases unchanged, no agent egress, and no availability signals (Claude's `allowed_warning` telemetry is no longer flagged).
- **Checks:** both forced timeouts stopped at 8.00 s with 0 processes left. Blocked access was denied (Codex 2 requests, Claude 1), with no content obtained.
- **Quota:** Claude 5-hour 46% to 50%, 7-day 25% to 26%. Codex 5-hour 9% to 11%, weekly 16%.

## Run bundle and EVALUATION_READY (2026-10-04 UTC)

- **Bundle:** `private/run_bundle/manifest.json`, contract `pilot1-bundle-v2`, sha256 `f82703f61ec19c55266dcc3e0b0ac5078c9b1d856ff24c4244f8ddb955b663db`. It was assembled by `scripts/assemble_run_bundle.py` from the third preflight and contains:
  - **Products** (identities from the controller's run records):
    - Codex: `codex-cli 0.160.0`, `gpt-6.1-sol`, effort high, observed in the session rollouts.
    - Claude Code: `2.1.289 (Claude Code)`, `claude-opus-5-5`, effort high requested; the product reports per-turn effort active but does not echo the level.
  - **Budget:** $0 approvals bound to the subscription-only decision note.
  - **Policies:** isolation (host sandbox, ID-44, with known limits) and failure (replacement only for evidenced infrastructure or availability events; quota pause).
  - **Runner binding** and the preflight references.
- **Schedule:** seed 20260931. r1 block order: Q12, Q03, Q07, Q14, Q26, Q27, Q16, Q17, Q04. r2 block order: Q03, Q04, Q26, Q16, Q12, Q07, Q27, Q14, Q17. Each product goes first in 9 of 18 blocks and in exactly one of each task's two blocks.
- **Tests:** full suite 432 passed, 42 skipped (host-only tests run on the host separately).
- **Certification:** `certify_build.py --dataset generated/pilot --scope evaluation` (deep, with independent rebuild) returned **`EVALUATION_READY`**.
- **Binding consequence:** any later change to the runner files, adapters, products.json, settings, product binaries, data freeze, grading policy, grader or gold invalidates this bundle. Formal runs must check the bundle before every slot.

## Formal wave driver (ID-46)

`scripts/run_wave.py` with `private/runners/wave.py`:
- **Order and resume:** runs the 36 slots strictly in bundle order and resumes from the append-only ledger `private/runs/wave/ledger.jsonl`.
- **Binding:** every slot is checked against the bundle before and after it runs.
- **Quota:** the 80%/95% gates were withdrawn by owner instruction (2026-10-04). The driver now runs until a window is exhausted and then waits for the reset. A run that hits the limit midway is an availability event, and its replacement waits for the provider's reset. Any paid-overage sign stops the wave. Owner-accepted driver changes are recorded in the ledger.
- **Outcomes and replacement:** structured availability evidence alone makes an outcome infrastructure. Each slot gets one replacement, at least 30 minutes after the failure and after the reset. Two consecutive infrastructure outcomes for a product stop the wave until `--acknowledge`.
- **Signals:** Ctrl-C lets the current run finish, then stops.
- **Sealing:** progress output only.

Tests: 17 on a fake controller (`tests/fixture_contracts/test_wave.py`). The live binding check passes on bundle `f82703f6…`. No formal slot has run.
