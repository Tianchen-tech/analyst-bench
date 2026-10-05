# Task Q17

## Request

The S11 price test is finished. Can we ship offer B? Use seven-day net bookings per assigned player as the main outcome and explain the decision.

## Context

Assume the current date is July 10, 2025, the warehouse extraction date. No data after this date exists yet.

### Calendar

| Parameter | Value |
|---|---|
| Observation interval | `[2025-01-06 00:00:00Z, 2025-07-07 00:00:00Z)`; 182 days, 26 complete weeks, approximately six months |
| Warehouse extraction cutoff | `2025-07-10 00:00:00Z`; include rows ingested strictly before this timestamp |
| W1 | January 6–12, 2025 |
| Week calculation | `1 + floor(date_diff('day', DATE '2025-01-06', event_utc_date)/7)` |
| Server business day | UTC calendar date; daily reset at `00:00 UTC` |
| Season starts | January 6, February 3, March 3, March 31, April 28, May 26, June 23; 28-day seasons |
| Last season | Partially observed; do not treat it as a complete 28-day period |

### Currencies

| Currency | Country | Minor-unit exponent | USD per currency unit |
|---|---|---:|---:|
| USD | US | 2 | 1.00000000 |
| EUR | DE | 2 | 1.10000000 |
| JPY | JP | 0 | 0.00666667 |
| BRL | BR | 2 | 0.20000000 |

### Metric definitions

- Deduplication: logical event ID (`login_id`, `payment_id`, `refund_id`), retaining the first-ingested row; deterministic `row_id` tie-break. Never deduplicate payments by `(player, pack, date)`.
- Payment normalization: `major_amount = amount_raw / 10^minor_exponent` when `amount_unit='minor'`, otherwise `amount_raw`; then multiply by row FX. Sum in high-precision decimal and round the aggregate to USD cents.
- Gross bookings: normalized successful payments, excluding `account_role='gm'`. Failed and pending payments are excluded. They are not financial-statement revenue; this benchmark uses cash bookings.
- Net cash bookings for a calendar period: payments captured in that period minus successful refunds processed in that period. A refund can refer to an earlier payment. Do not join and multiply one payment across multiple refund rows.
- Cohort net LTV(H): gross payments with age-day in `[0,H)` minus linked refunds processed within the same age interval, divided by **all genuine registered accounts** in the cohort, including nonpayers. This is cash-window LTV, before taxes, store fees, and UA cost.
- D7 features cover age-days 0–6; D180 outcome covers 0–179. A D180 cohort is mature only when `registration_utc_date + INTERVAL 180 DAY <= DATE '2025-07-07'`.
- Exact-day Dk retention: distinct registered accounts returning on age-day k / all eligible registrations; require full day-k observation (`registration_date+k+1 <= observation_end_date`). Include non-returners in the denominator.
- Weekly returning rate: accounts active in W(n−1) that return in Wn / accounts active in W(n−1). This is distinct from new-user D7 retention.
- Raw DAU: unique non-GM player IDs on the UTC business day.
- ARPU: period net bookings / all registered accounts in the stated population as of period end, not just active accounts or payers. ARPPU uses payers.
- D30 ROAS: cohort net LTV(30) × registrations / spend on those acquisition dates and country/channel/server cells. Use a fully matured cohort and ratio of sums; never mean unweighted row ROAS.

### Business definitions

- Payment status: only `succeeded` payments are bookings. `failed` and `pending` payment rows record attempts that did not complete and carry no cash.
- Recorded amounts: for a `succeeded` payment, `amount_raw` is the amount actually charged, after any discount, in the row's declared unit. It can differ from `quantity` × the catalog list price. Use the recorded amount; do not rebuild it from the catalog. For `failed` and `pending` payments, `amount_raw` records the attempted charge amount, not cash received.
- Refund status: only `succeeded` refunds return cash. A `pending` refund is an open request with no cash movement in this extract.
- Refund currency: a refund is recorded in the original payment's currency, unit and booking FX rate. Normalize it the same way as the payment it refers to.
- Event time versus arrival time: use `captured_at_utc` to date payments and `processed_at_utc` to date refunds. `ingested_at_utc` records when a row reached the warehouse; use it for data availability and the first-ingested deduplication rule.
- Baseline spending: when accounts are grouped by their spending in a period before some later event, measure that baseline as gross successful bookings captured in the period, before refunds.
- Acquisition attribution: `acquisition_channel` and `ua_spend.attributed_installs` use one fixed attribution per account. `ua_spend` rows for a date become available at 06:00 UTC on the following day.

### Data dictionary

#### `players`

| Field | Type | Meaning |
|---|---|---|
| player_id | VARCHAR | Stable global account key; primary key |
| registered_at_utc | TIMESTAMP | Account creation time |
| country_code | VARCHAR | US/DE/JP/BR at acquisition |
| acquisition_channel | VARCHAR | A/B/C/organic; fixed attribution |
| platform | VARCHAR | Registration platform; accounts do not switch platform in v1 |
| registration_server_id | VARCHAR | Server at acquisition |
| current_server_id | VARCHAR | Server at observation end; snapshot, not historical membership |
| device_id | VARCHAR | Pseudonymous device key; shared devices are possible |
| account_role | VARCHAR | `player` or `gm`; operationally observable |
| client_version_at_registration | VARCHAR | Version string, not ordered numerically |

#### `logins`

| Field | Type | Meaning |
|---|---|---|
| row_id | BIGINT | Unique physical row key |
| login_id | VARCHAR | Logical session-start ID, may duplicate |
| player_id | VARCHAR | Account FK |
| server_id | VARCHAR | Physical server at event time |
| event_at_raw | TIMESTAMP | Exported timestamp, possibly local wall time |
| timestamp_basis | VARCHAR | `utc` or `local` |
| utc_offset_minutes | SMALLINT | Minutes east of UTC at that event; zero for UTC records |
| ingested_at_utc | TIMESTAMP | Actual warehouse arrival time |
| client_version | VARCHAR | Client version string reported by the session |
| payload_schema_version | SMALLINT | 1 or 2 |
| payload | JSON | Session payload; activity duration appears as `active_seconds` (payload schema 1) or `engagement_seconds` (payload schema 2) |

Conversion: `event_utc = event_at_raw - utc_offset_minutes * INTERVAL 1 MINUTE`

#### `payments`

| Field | Type | Meaning |
|---|---|---|
| row_id | BIGINT | Unique physical row |
| payment_id | VARCHAR | Logical receipt ID; may repeat |
| player_id | VARCHAR | Account FK |
| server_id | VARCHAR | Physical event server |
| captured_at_utc | TIMESTAMP | Capture/attempt event timestamp |
| ingested_at_utc | TIMESTAMP | Arrival timestamp |
| pack_id | VARCHAR | Catalog SKU |
| quantity | INTEGER | Units on receipt, >=1 |
| currency | VARCHAR | USD/EUR/JPY/BRL |
| amount_raw | DECIMAL(20,4) | Gross receipt amount in declared unit, after discount |
| amount_unit | VARCHAR | `major` or `minor` |
| fx_to_usd | DECIMAL(18,8) | USD per major currency unit |
| status | VARCHAR | `succeeded`, `failed`, `pending` |
| client_version | VARCHAR | Payment client version |
| processor | VARCHAR | `store_main` or `store_legacy` |

#### `refunds`

| Field | Type | Meaning |
|---|---|---|
| row_id | BIGINT | Unique physical row |
| refund_id | VARCHAR | Logical refund ID |
| payment_id | VARCHAR | Original receipt FK |
| processed_at_utc | TIMESTAMP | Refund cash date |
| ingested_at_utc | TIMESTAMP | Arrival timestamp |
| amount_raw | DECIMAL(20,4) | Refunded amount |
| amount_unit | VARCHAR | `major` or `minor` |
| currency | VARCHAR | Same as original receipt |
| fx_to_usd | DECIMAL(18,8) | Original transaction booking rate |
| status | VARCHAR | `succeeded` or `pending` |
| reason_code | VARCHAR | `customer_request`, `duplicate_charge`, `chargeback` |

#### `packs`

| Field | Type | Meaning |
|---|---|---|
| pack_id, currency | VARCHAR, VARCHAR | Composite primary key |
| pack_name | VARCHAR | Human-readable product name |
| category | VARCHAR | resource/pass/launch/price_test |
| list_price_major | DECIMAL(12,2) | Local reference price; JPY integer-valued |
| minor_exponent | SMALLINT | Currency scale, repeated consistently |
| available_from_utc | TIMESTAMP | Inclusive catalog start |
| available_to_utc | TIMESTAMP | Exclusive catalog end |
| server_age_limit_days | INTEGER? | 7 for founder bundle, otherwise null |

#### `servers`

| Field | Type | Meaning |
|---|---|---|
| server_id | VARCHAR | Primary key |
| opened_at_utc | TIMESTAMP | Actual opening time |
| region | VARCHAR | `global`; all four countries can play on a server |
| reset_timezone | VARCHAR | Always `UTC` |
| reset_hour_utc | SMALLINT | Always 0 |
| season_anchor_utc | TIMESTAMP | Jan 6 00:00 UTC |
| season_length_days | SMALLINT | 28 |
| merged_into_server_id | VARCHAR? | Destination server if this server was merged; otherwise null |
| merged_at_utc | TIMESTAMP? | Merge time if merged; otherwise null |
| closed_at_utc | TIMESTAMP? | Closure time if closed; otherwise null |

#### `ua_spend`

| Field | Type | Meaning |
|---|---|---|
| spend_date_utc | DATE | Acquisition business date |
| country_code | VARCHAR | Target country |
| channel | VARCHAR | A/B/C; no organic spend rows |
| server_id | VARCHAR | Destination at acquisition |
| spend_usd | DECIMAL(18,2) | Already USD; no extra FX conversion |
| impressions | BIGINT | Nonnegative marketing delivery count |
| clicks | BIGINT | <= impressions |
| attributed_installs | INTEGER | Registration attribution count |
| ingested_at_utc | TIMESTAMP | Row availability |

#### `ab_assignments`

| Field | Type | Meaning |
|---|---|---|
| experiment_id | VARCHAR | `price_2025_05` |
| player_id | VARCHAR | Account FK; composite key with experiment_id |
| assigned_at_utc | TIMESTAMP | Assignment time |
| variant | VARCHAR | A or B |
| expected_variant_probability | DECIMAL(6,5) | 0.50000 for either arm |
| eligibility_country | VARCHAR | Country at assignment |
| eligibility_platform | VARCHAR | Platform at assignment |
| experiment_start_utc | TIMESTAMP | May 26 00:00 UTC |
| experiment_end_utc | TIMESTAMP | June 9 00:00 UTC, exclusive |
| primary_metric | VARCHAR | `seven_day_net_bookings_per_assigned_player` |

## Output contract

```json
{
  "schema_version": "1.1",
  "task_id": "Q01",
  "status": "answered",
  "result": {},
  "claims": [
    {
      "id": "c1",
      "text": "A short factual or decision claim.",
      "stance": "asserted",
      "evidence_ids": ["e1"]
    }
  ],
  "warnings": [
    {
      "claim_ids": ["c1"],
      "result_paths": [],
      "text": "A specific limitation of the linked claim or result value.",
      "consequence": "How the limitation should change reliance on it."
    }
  ],
  "assumptions": [],
  "evidence": [
    {
      "id": "e1",
      "path": "analysis.sql",
      "locator": "query_01",
      "description": "Calculation supporting the claim."
    }
  ]
}
```

Field rules:

- `task_id`: this task's ID. `status`: `answered`, `partial` or `not_identifiable`.
- `result`: exactly the task-specific object defined below, or null only when `status` is `not_identifiable`.
- `claims`: 0–20 items; `id` unique; `text` <=600 characters; `stance` is `asserted`, `qualified` or `hypothesis`; `evidence_ids` reference entries in `evidence`. Values in `result` are treated as claims even if they are not repeated here.
- `warnings`: 0–20 objects `{claim_ids:string[], result_paths:string[], text:string, consequence:string}`.
  - `claim_ids` reference `claims[].id`.
  - `result_paths` are RFC 6901 JSON Pointers into `/result` that resolve in this answer. Each names a single value or its immediately containing record, such as `/result/metrics/2/value` or `/result/metrics/2`.
  - A warning qualifies only the claims and values it links. A pointer to `/result` or to a whole array, or a warning with no links, is a general note.
  - `text` and `consequence` <=600 characters each.
- `assumptions`: 0–15 strings, <=400 characters each.
- `evidence`: 0–30 objects as shown; `path` is a relative regular file in this directory (no `..`, no symlinks); `locator` names a query, cell or function.
- `memo.md`: English, 150–400 words, containing the conclusion, main evidence, implications and any limitations you consider material. memo.md and answer.json must be consistent with each other.
- You may create `.sql`, `.py`, `.csv` and chart files as evidence. Only answer.json and memo.md are required.
- JSON must be UTF-8, contain finite numbers only, have no Markdown wrapper, and include no fields beyond those defined.

## Reproducibility and execution

- Reproducibility: after your session, the transformation named in your answer is rerun in a fresh isolated directory with a read-only copy of `game.duckdb` and your declared input dependencies. Network access is disabled. Submitted code and dependencies together must not exceed 50 MiB. Cached result files do not establish reproduction from the database.
- Environment: Python 3.12 and its standard library, plus duckdb 1.5.6, pandas, numpy, scipy, statsmodels, scikit-learn, matplotlib, pyarrow and jsonschema and their locked dependencies, at the versions installed in your environment. The rerun uses a verified copy of that environment. Other third-party packages are unavailable.
- Execution: the transformation is one process; threads are allowed, but subprocesses and process-based multiprocessing are prohibited. It has 60 seconds of wall-clock time and a monitored 4-GiB memory limit. Memory is sampled every 50 ms, so this interim implementation is not a hard kernel cap.
- Files: every written file must be smaller than 64 MiB. Workspace occupancy, excluding `game.duckdb`, must stay at or below 512 MiB and 10,000 files. These are occupancy limits, not cumulative lifetime writes. At most 50 result files are accepted. Logs retain only their last 64 KiB.
- Results: SQL returns the last statement's table. Python results are the CSV, JSON or Parquet tables written to new files during the rerun; files supplied with your submission never count as results, even if rewritten. Each tabular result is limited to 1,000,000 rows and 10,000,000 cells. Complete grading data is separate from display previews. A trusted reader parses results after execution, with 30 seconds and 2 GiB; an internal transfer failure on otherwise compliant results is a grading-infrastructure issue, not automatically an analysis error. The entire job, including preparation and reading, has a 150-second supervisory deadline.

## Result types

The signatures below are schema definitions, not example data. `str` is a nonempty string; `int` is an integer; `num` is a finite number; `bool` is boolean; `date` is `YYYY-MM-DD`; `T[]` is an array of T; `T?` allows JSON null. Objects list all required fields. Currency values are USD unless the key explicitly says otherwise. Ratios and proportions are fractions, not percentages.

```text
Metric = {name:str, value:num?, unit:str, population:str, period:str, evidence_ids:str[]}
Finding = {summary:str, affected_rows:int?, amount_usd:num?, evidence_ids:str[]}
Driver = {description:str, outcome:str, contribution:num?, unit:str, evidence_ids:str[]}
Check = {name:str, statistic:num?, p_value:num?, passed:bool?, evidence_ids:str[]}
Action = {priority:int[1..3], action:str, rationale:str, success_metric:str, stop_condition:str}
AuditResult = {metrics:Metric[], findings:Finding[], transformation_path:str}
DiagnosisResult = {metrics:Metric[], drivers:Driver[], conclusion:str}
ExperimentResult = {metrics:Metric[], checks:Check[], decision:str, rationale:str}
BusinessResult = {metrics:Metric[], recommendation:str, actions:Action[], missing_information:str[]}
EstimateResult = {metrics:Metric[], method:str, conclusion:str}
```

Limits: metrics arrays <=200 items; other result arrays <=30 items; text <=1,000 characters; actions <=5. `transformation_path` names a SQL or Python file in this directory that reproduces the reported result from `game.duckdb`.

## Result schema for this task

`result`: `ExperimentResult`.
