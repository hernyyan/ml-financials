status: ready-for-agent

# Fabric → Bronze Sync Pipeline

## Problem Statement

Portfolio company financial statement data lives in Fabric's `smc_dwh` warehouse in an EAV shape (one row per company/period/line-item/scenario), spread across a much larger universe of line items than the firm's current monitoring template actually uses — including retired items still present in the source and no enforced scope on which companies should be tracked. There is currently no queryable, standardized store of this data, and no way to tell, for a given company and period, whether the financial statements that should exist actually do, or whether they're missing or effectively blank.

## Solution

Build a bronze-layer Postgres pipeline that:
- Pulls exactly the 47 confirmed, current-template financial statement line items (Income Statement, Balance Sheet, Cash Flow) from Fabric's `production.base_ilevel__periodic_data`, filtered to `scenario = 'Actual'` and to a manually maintained allowlist of 53 portfolio companies.
- Pivots the EAV rows into three wide bronze tables (one row per company/period), preserving the distinction between a genuinely-submitted zero and a missing value.
- Exposes a completeness view so gaps and effectively-empty statements can be found and backfilled without manually querying bronze.

## User Stories

1. As the pipeline operator, I want the sync to only pull data for companies on a manually maintained allowlist, so that we never silently ingest financials for companies outside current monitoring scope.
2. As the pipeline operator, I want the allowlist matched by Fabric's numeric `investment_id`, not by company name, so that a company renaming itself in Fabric doesn't break or silently drop its sync.
3. As the pipeline operator, I want two Fabric records for the same real-world company (e.g., an "(old)" legacy record) to be trackable as distinct allowlist entries, so that historical data under a superseded id isn't silently lost or conflated with the current id.
4. As the pipeline operator, I want the sync to only pull the 47 line items confirmed against the current monitoring template, so that retired ("OLD DO NOT USE") and out-of-scope line items never enter bronze.
5. As the pipeline operator, I want line items matched by Fabric's `data_item_id`, not by name, so that a line item renamed in Fabric under a stable id doesn't silently break the mapping.
6. As the pipeline operator, I want the sync filtered to `scenario = 'Actual'` only, so that Budget/Forecast/other scenario data never contaminates bronze.
7. As the pipeline operator, I want the EAV rows pivoted into one wide row per company/period per statement, so that bronze is directly queryable as a financial statement rather than requiring a pivot on every read.
8. As the pipeline operator, I want a data item that was never submitted for a company/period to appear as `NULL`, and a data item that was submitted with a real value of `0` to appear as `0`, so that "missing" and "genuinely zero" are never confused downstream.
9. As the pipeline operator, I want re-running the sync for a company/period that already has a bronze row to update that row in place (upsert on `company_id, period_end`), so that re-syncs are idempotent and don't create duplicates.
10. As the pipeline operator, I want every row touched by a sync run stamped with a timestamp-based batch id, so that I can identify or roll back everything a specific run touched.
11. As the pipeline operator, I want `company_id` typed as `INTEGER` everywhere it appears (bronze tables, `public.companies`, `public.company_sync_list`), so that joins between these tables never require implicit casting.
12. As the pipeline operator, I want a completeness view showing, per company/period/statement, how many of the expected line items are filled versus expected, so that I can quickly see which statements are incomplete.
13. As the pipeline operator, I want that same view to flag a statement as `is_empty` when every one of its values is `NULL` or `0`, so that I can distinguish a placeholder/blank load from a merely-incomplete one, even when the raw fill-count looks high.
14. As the pipeline operator, I want the completeness view to always reflect the live state of bronze with no separate sync step, so that it can never drift out of date the way a manually maintained summary table could.
15. As the pipeline operator, I want the sync triggered manually (not on a schedule), so that I retain control over when Fabric credentials are used and when bronze changes.
16. As a future maintainer, I want the Fabric `data_item_id` documented alongside each bronze column, so that the mapping from source to schema is traceable without re-deriving it from scratch.

## Implementation Decisions

- **Source query**: `production.base_ilevel__periodic_data` filtered server-side by `periodic_data_data_item_id IN (<47 confirmed ids>)`, `periodic_data_investment_id IN (<ids from company_sync_list>)`, and `periodic_data_scenario = 'Actual'`. The company id list is read from `public.company_sync_list` before the Fabric query is built, so both filters apply in the same query rather than pulling all companies and filtering client-side.
- **Bronze schema** (`bronze.income_statement`, `bronze.balance_sheet`, `bronze.cash_flow`, already migrated via `001_bronze_schema.sql`): one column per confirmed line item (15 / 28 / 4 respectively), `company_id INTEGER`, `period_end DATE`, `UNIQUE (company_id, period_end)`, provenance columns (`source_system`, `loaded_at`, `source_batch_id`). Each column carries its source `data_item_id` as an inline comment for traceability.
- **Pivot**: performed in Python, not SQL — a static `{data_item_id: column_name}` dict groups the fetched EAV rows by `(investment_id, period_end)` and builds one wide record per group. Chosen over a generated SQL `CASE WHEN` pivot because the mapping is easier to read and edit in Python when the template changes again.
- **Null vs. zero handling**: the pivot must use `is not None` checks when assigning values to columns, never a truthy check (`value or None`), since `0` is falsy in Python and would otherwise be silently coalesced into `NULL`.
- **Partial rows allowed**: a company/period row is inserted into bronze as soon as any of its line items are present; missing items are `NULL`. No completeness threshold gates insertion — that's a downstream (view) concern, not a bronze-ingestion concern.
- **Upsert**: `INSERT ... ON CONFLICT (company_id, period_end) DO UPDATE` per bronze table.
- **`source_batch_id`**: a timestamp-based id (e.g. `20260721_143000`) generated once per sync run and stamped onto every row the run inserts or updates.
- **Company allowlist** (`public.company_sync_list`, already migrated via `002_company_sync_list.sql`): `company_id INTEGER PRIMARY KEY`, `company_name TEXT NOT NULL`. Manually maintained only — never derived from `base_ilevel__assets` or any Fabric query. Currently seeded with 53 rows (the confirmed 52 portfolio companies plus a distinct row for a legacy Fabric record — `Delva Master Holdings (old)`, investment_id 3541 — tracked separately from the current `Delva Master Holdings`, investment_id 486, per an explicit decision to treat them as two companies rather than reconcile them). Lives in `public`, not a separate `meta` schema — the extra schema was considered and rejected as unwarranted complexity at this project's scale (one operator, one Postgres role, no access-control or namespace-collision need).
- **Type consistency**: `company_id` is `INTEGER` across `bronze.*`, `public.companies`, and `public.company_sync_list` (not `TEXT`, which was the original pre-drafted schema's type before this decision).
- **Completeness view** (`public.statement_completeness`, not yet built): `UNION ALL` across the three bronze tables, one row per `(company_id, company_name, statement_type, period_end)`. `statement_type` is plain text with a `CHECK` constraint (`income_statement`, `balance_sheet`, `cash_flow_statement`) — no lookup/id table, since the value set is fixed at 3 and will not grow. `count_filled` = number of non-`NULL` columns for that statement (a `0` counts as filled). `count_total` = fixed constant per statement type (15 / 28 / 4). `is_empty` = true only when every column for that statement is `NULL` or `0` — a distinct, stricter signal than `count_filled`/`count_total`, intended to catch a fully-populated-but-all-zero placeholder load that would otherwise look complete by count alone. Implemented as a plain (non-materialized) SQL view, not a separate table with triggers — a view is inherently always current with no sync/trigger logic to maintain or drift, and bronze's data volume (53 companies × a few hundred periods at most) is far too small to need pre-computed results.
- **Auth/connectivity**: Fabric via `pyodbc` + `azure-identity` `ClientSecretCredential` (env: `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`, `FABRIC_TENANT_ID`, `FABRIC_SQL_ENDPOINT`, `FABRIC_DATABASE`). Postgres via `psycopg2`, authenticated with a short-lived Entra ID access token as the password (regenerated via `az account get-access-token --resource-type oss-rdbms`), env: `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`.
- **Trigger model**: manual only. The operator runs the sync script on demand with live Fabric credentials; there is no scheduler.

## Testing Decisions

- Good tests here exercise external behavior — given a set of raw EAV rows, does the pivot produce the correct wide record (including the null-vs-zero edge case), and given a set of bronze rows, does the completeness view report the correct `count_filled`/`count_total`/`is_empty` — not internal implementation details of how the grouping dict is built.
- **Pivot function**: unit-testable as a pure function (list of EAV rows in, dict per `(company_id, period_end)` out) with no Fabric/Postgres dependency — test cases should specifically cover: a fully populated period, a partially populated period, a period where a real item is `0`, and a period missing that same item entirely, asserting the two are never confused.
- **Completeness view**: tested against a small fixture set of rows inserted into a scratch/temp schema (or a transaction rolled back after assertion), covering: a fully filled statement, a statement with some `NULL`s (correct `count_filled` less than `count_total`), and a statement where every value is `NULL`-or-`0` (asserting `is_empty = true` even when `count_filled` is high).
- No prior art in this repo — it's a greenfield Python/SQL project. `pytest` is the natural choice given the existing `python-dotenv`/`pyodbc`/`psycopg2` stack.
- Out of scope for testing: a live integration test against real Fabric/Postgres credentials — the unit/fixture-based tests above are sufficient, and running against production Fabric/Postgres from a test suite is unnecessary risk.

## Out of Scope

- The iLEVEL REST API as a data source — explored and reverted; Fabric remains the source of truth for this pipeline.
- Reconciling or backfilling the retired "OLD DO NOT USE" line items (10729, 10036, 10724, 10725, 10033, 10063) or any other Fabric data item outside the 47 confirmed current-template items — explicitly out of scope now that the confirmed 47-item list is the only target.
- Automated/scheduled syncing — the trigger remains manual for the foreseeable future.
- Silver and gold layer transformations, and the two-engine (deterministic/probabilistic) monitoring logic described in the original project handoff — this spec covers bronze ingestion only.
- Investigating or backfilling data under `Delva Master Holdings (old)` (investment_id 3541) — it is tracked as a distinct allowlist entry but no further reconciliation work against it is planned here.
- A `meta` schema for pipeline observability — considered and explicitly rejected; `company_sync_list` and `statement_completeness` both live in `public`.

## Further Notes

- Three known Fabric name variants map to a single `investment_id` each (Built by Grid / "Built by Grid, LLC" → 3605; The Clean People / "The Clean People LLC" / "The Clean People, LLC" → 3670; The Stonewall Group / "The Stonewall Group LLC" → 3623). These are informational only — `company_sync_list` stores a single name per id and matching is by id, so no variant-tracking column exists or is needed.
- `public.companies` (the richer dimension table with hold_date/exit_date/status/sector_code/cluster_id) is a separate, pre-existing concern from `company_sync_list` and is not modified by this spec beyond the `company_id` type change to `INTEGER`.
- Migrations `001_bronze_schema.sql` and `002_company_sync_list.sql` have already been run against the live `portfolio_monitoring` database; the `company_id` type change (INTEGER) and the new `statement_completeness` view are not yet migrated.
