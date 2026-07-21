# ml-financials

Bronze-layer pipeline that syncs portfolio company financials from Fabric's
`smc_dwh` warehouse into Postgres, pivoted from EAV rows into wide
income statement / balance sheet / cash flow tables.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `FABRIC_CLIENT_ID` / `FABRIC_CLIENT_SECRET` / `FABRIC_TENANT_ID` / `FABRIC_SQL_ENDPOINT` / `FABRIC_DATABASE` — Fabric service principal creds.
- `PG_HOST` / `PG_PORT` / `PG_DATABASE` / `PG_USER` — already filled in; leave as-is.
- `PG_PASSWORD` — a short-lived Entra ID access token, **not** a static password. Regenerate before each session:
  ```bash
  az login --tenant cd42ad31-bf24-4569-91e9-e4e961d2a99c --allow-no-subscriptions
  az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv | Set-Clipboard
  ```
  Paste the output into `PG_PASSWORD`.

## Running a sync

```bash
# one allowlisted company
python scripts/bronze_sync.py <company_id>

# every allowlisted company (all of public.company_sync_list)
python scripts/bronze_sync.py
```

Syncing is manual (no scheduler) and idempotent — re-running upserts existing
`(company_id, period_end)` rows rather than duplicating them. A company with
no periodic data in Fabric is not an error; it just produces no rows.

Each run pulls the confirmed financial-statement line items, filtered to
`scenario = 'Actual'`, for companies on `public.company_sync_list`. Adding or
removing a company from that table changes what future syncs cover.

## Querying the data

Connect with the same `PG_*` values from `.env` (password = the Entra token above):

```bash
psql "host=$env:PG_HOST port=$env:PG_PORT dbname=$env:PG_DATABASE user=$env:PG_USER sslmode=require"
```

or any Postgres GUI client (Azure Data Studio, DBeaver, TablePlus) with the
same host/port/db/user and SSL required.

Key tables/views:
- `bronze.income_statement`, `bronze.balance_sheet`, `bronze.cash_flow` — one row per `(company_id, period_end)`.
- `public.statement_completeness` — coverage/gap triage view (`count_filled`, `count_total`, `is_empty`). Example:
  ```sql
  SELECT * FROM public.statement_completeness
  WHERE is_empty OR count_filled < count_total
  ORDER BY company_name, period_end;
  ```
- `public.company_sync_list` — the manually maintained sync allowlist.

## Tests

```bash
python -m pytest
```

Pivot-logic tests are pure Python (no Fabric/Postgres dependency).
`statement_completeness` tests run against real Postgres inside a rolled-back
transaction (see `tests/conftest.py`) — requires `.env` to be configured.

## Issue tracking

See `docs/agents/issue-tracker.md` — issues live in GitHub Issues on
`Star-Mountain-Capital/ml-financials`.
