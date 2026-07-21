"""
Manual sync: pulls the 47 confirmed financial-statement line items for
allowlisted companies from Fabric's production.base_ilevel__periodic_data,
pivots the EAV rows into wide records, and upserts them into
bronze.income_statement / balance_sheet / cash_flow.

Usage:
    python scripts/bronze_sync.py <company_id>   # sync one allowlisted company
    python scripts/bronze_sync.py                # sync every company in company_sync_list
"""
import argparse
import os
import struct
import time
from datetime import datetime, timezone

import psycopg2
import pyodbc
from azure.identity import ClientSecretCredential
from dotenv import load_dotenv

load_dotenv()

FABRIC_SCOPE = "https://database.windows.net/.default"
SQL_COPT_SS_ACCESS_TOKEN = 1256

# data_item_id -> (bronze table, column). Static per issue #1's Implementation
# Decisions: a Python dict is easier to read/edit than a generated SQL pivot
# when the confirmed-item template changes. Each id's source name (from
# production.base_ilevel__data_items) is noted alongside for traceability.
DATA_ITEM_COLUMN_MAP = {
    # income_statement
    10717: ("income_statement", "total_revenue"),                    # Total Revenue
    10001: ("income_statement", "cogs"),                              # COGS
    11679: ("income_statement", "gross_profit"),                      # Gross Profit
    11680: ("income_statement", "total_operating_expenses"),          # Total Operating Expenses
    11682: ("income_statement", "ebitda_standard"),                   # EBITDA - Standard
    10059: ("income_statement", "ebitda_adjustments"),                # EBITDA Adjustments
    11705: ("income_statement", "adjusted_ebitda_standard"),          # Adjusted EBITDA - Standard
    10004: ("income_statement", "depreciation_amortization"),         # Depreciation & Amortization
    10012: ("income_statement", "interest_expense_income"),           # Interest Expense/(Income)
    12190: ("income_statement", "other_expense_income"),              # Other Expense / (Income)
    10014: ("income_statement", "taxes"),                             # Taxes
    11683: ("income_statement", "net_income"),                        # Net Income (Loss)
    12212: ("income_statement", "equity_cure"),                       # Equity Cure
    12211: ("income_statement", "adjusted_ebitda_including_cures"),   # Adjusted EBITDA - Including Cures
    10722: ("income_statement", "covenant_ebitda"),                   # Covenant EBITDA
    # balance_sheet
    10016: ("balance_sheet", "cash_and_equivalents"),                 # Cash & Cash Equivalents
    10017: ("balance_sheet", "accounts_receivable"),                  # Accounts Receivable
    10269: ("balance_sheet", "inventory"),                            # Inventory
    10018: ("balance_sheet", "prepaid_expenses"),                     # Prepaid Expenses
    10020: ("balance_sheet", "other_current_assets"),                 # Other Current Assets
    11684: ("balance_sheet", "total_current_assets"),                 # Total Current Assets
    10270: ("balance_sheet", "property_plant_equipment"),             # Property, Plant & Equipment
    10271: ("balance_sheet", "accumulated_depreciation"),              # Accumulated Depreciation
    10023: ("balance_sheet", "goodwill_intangibles"),                 # Goodwill & Intangibles
    10025: ("balance_sheet", "other_non_current_assets"),              # Other Non-Current Assets
    11686: ("balance_sheet", "total_non_current_assets"),              # Total Non-Current Assets
    11687: ("balance_sheet", "total_assets"),                         # Total Assets
    10028: ("balance_sheet", "accounts_payable"),                     # Accounts Payable
    10030: ("balance_sheet", "accrued_liabilities"),                  # Accrued Liabilities
    10031: ("balance_sheet", "deferred_revenue"),                     # Deferred Revenue
    10730: ("balance_sheet", "revolver_balance_sheet"),               # Revolver - Balance Sheet
    12179: ("balance_sheet", "current_maturities"),                   # Current Maturities
    10032: ("balance_sheet", "other_current_liabilities"),             # Other Current Liabilities
    12192: ("balance_sheet", "total_current_liabilities"),             # Total Current Liabilities
    10728: ("balance_sheet", "long_term_loans"),                      # Long Term Loans
    10727: ("balance_sheet", "long_term_leases"),                     # Long Term Leases
    12191: ("balance_sheet", "other_non_current_liabilities"),        # Other Non-Current Liabilities
    12194: ("balance_sheet", "total_non_current_liabilities"),        # Total Non-Current Liabilities
    11689: ("balance_sheet", "total_liabilities"),                    # Total Liabilities
    10040: ("balance_sheet", "paid_in_capital"),                      # Paid In Capital
    10041: ("balance_sheet", "retained_earnings"),                    # Retained Earnings
    12193: ("balance_sheet", "other_equity"),                         # Other Equity
    11690: ("balance_sheet", "total_equity"),                         # Total Equity
    # cash_flow
    10047: ("cash_flow", "operating_cash_flow"),                      # Operating Cash Flow
    10048: ("cash_flow", "investing_cash_flow"),                      # Investing Cash Flow
    10049: ("cash_flow", "financing_cash_flow"),                      # Financing Cash Flow
    10292: ("cash_flow", "capex"),                                    # CAPEX
}

TABLE_COLUMNS = {
    "income_statement": [
        "total_revenue", "cogs", "gross_profit", "total_operating_expenses",
        "ebitda_standard", "ebitda_adjustments", "adjusted_ebitda_standard",
        "depreciation_amortization", "interest_expense_income", "other_expense_income",
        "taxes", "net_income", "equity_cure", "adjusted_ebitda_including_cures",
        "covenant_ebitda",
    ],
    "balance_sheet": [
        "cash_and_equivalents", "accounts_receivable", "inventory", "prepaid_expenses",
        "other_current_assets", "total_current_assets", "property_plant_equipment",
        "accumulated_depreciation", "goodwill_intangibles", "other_non_current_assets",
        "total_non_current_assets", "total_assets", "accounts_payable", "accrued_liabilities",
        "deferred_revenue", "revolver_balance_sheet", "current_maturities",
        "other_current_liabilities", "total_current_liabilities", "long_term_loans",
        "long_term_leases", "other_non_current_liabilities", "total_non_current_liabilities",
        "total_liabilities", "paid_in_capital", "retained_earnings", "other_equity",
        "total_equity",
    ],
    "cash_flow": ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "capex"],
}

CONFIRMED_DATA_ITEM_IDS = list(DATA_ITEM_COLUMN_MAP)


def pivot_periodic_rows(rows, company_id, company_name):
    """
    rows: iterable of (data_item_id, period_end, value) for a single company.
    Returns {table_name: [record_dict, ...]}, one record per period_end seen,
    with every confirmed column for that table present -- filled with its
    value if submitted, None if never submitted for that period. `value` is
    checked with `is not None`, never a truthy check, so a genuine 0 is never
    coalesced into NULL.
    """
    values_by_table_period = {table: {} for table in TABLE_COLUMNS}

    for data_item_id, period_end, value in rows:
        mapping = DATA_ITEM_COLUMN_MAP.get(data_item_id)
        if mapping is None:
            continue
        table, column = mapping
        period_values = values_by_table_period[table].setdefault(period_end, {})
        if value is not None:
            period_values[column] = value

    result = {}
    for table, columns in TABLE_COLUMNS.items():
        records = []
        for period_end, values in values_by_table_period[table].items():
            record = {"company_id": company_id, "company_name": company_name, "period_end": period_end}
            for column in columns:
                record[column] = values.get(column)
            records.append(record)
        result[table] = records
    return result


def generate_batch_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def get_fabric_connection():
    credential = ClientSecretCredential(
        tenant_id=os.environ["FABRIC_TENANT_ID"],
        client_id=os.environ["FABRIC_CLIENT_ID"],
        client_secret=os.environ["FABRIC_CLIENT_SECRET"],
    )
    token = credential.get_token(FABRIC_SCOPE).token
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={os.environ['FABRIC_SQL_ENDPOINT']},1433;"
        f"Database={os.environ['FABRIC_DATABASE']};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})


def get_pg_connection():
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
        dbname=os.environ["PG_DATABASE"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        sslmode="require",
    )


def load_company_name(pg_conn, company_id):
    """Raises ValueError if company_id is not on the allowlist."""
    cur = pg_conn.cursor()
    cur.execute("SELECT company_name FROM public.company_sync_list WHERE company_id = %s", (company_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"company_id {company_id} is not on public.company_sync_list")
    return row[0]


def fetch_all_company_ids(pg_conn):
    cur = pg_conn.cursor()
    cur.execute("SELECT company_id FROM public.company_sync_list ORDER BY company_id")
    return [row[0] for row in cur.fetchall()]


def fetch_periodic_data(fabric_conn, company_id):
    """Returns list of (data_item_id, period_end, value) for one company,
    scenario='Actual', restricted server-side to the 47 confirmed items."""
    placeholders = ",".join(str(i) for i in CONFIRMED_DATA_ITEM_IDS)
    cursor = fabric_conn.cursor()
    cursor.execute(
        f"""
        SELECT periodic_data_data_item_id, periodic_data_period_end, periodic_data_value
        FROM production.base_ilevel__periodic_data
        WHERE periodic_data_scenario = 'Actual'
          AND periodic_data_investment_id = ?
          AND periodic_data_data_item_id IN ({placeholders})
        """,
        (company_id,),
    )
    return cursor.fetchall()


def upsert_records(pg_conn, table, records, batch_id):
    if not records:
        return
    columns = ["company_id", "company_name", "period_end", *TABLE_COLUMNS[table], "source_batch_id"]
    placeholders = ", ".join(f"%({c})s" for c in columns)
    update_columns = ["company_name", *TABLE_COLUMNS[table], "source_batch_id", "loaded_at"]
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns if c != "loaded_at")
    update_clause += ", loaded_at = now()"

    cur = pg_conn.cursor()
    for record in records:
        row = {**record, "source_batch_id": batch_id}
        cur.execute(
            f"""
            INSERT INTO bronze.{table} ({", ".join(columns)}, loaded_at)
            VALUES ({placeholders}, now())
            ON CONFLICT (company_id, period_end) DO UPDATE SET {update_clause}
            """,
            row,
        )


def sync_company_with_conns(company_id, pg_conn, fabric_conn, batch_id):
    """
    Syncs one company using already-open connections and a shared batch_id --
    the unit of work reused by both single-company and full-portfolio runs.
    A company with no periodic data in Fabric simply produces zero records
    per table; it is not an error.
    """
    company_name = load_company_name(pg_conn, company_id)
    rows = fetch_periodic_data(fabric_conn, company_id)
    pivoted = pivot_periodic_rows(rows, company_id, company_name)
    try:
        for table, records in pivoted.items():
            upsert_records(pg_conn, table, records, batch_id)
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise

    return {
        "company_name": company_name,
        "periods_synced": {table: len(records) for table, records in pivoted.items()},
    }


def sync_company(company_id):
    batch_id = generate_batch_id()

    pg_conn = get_pg_connection()
    try:
        fabric_conn = get_fabric_connection()
        try:
            summary = sync_company_with_conns(company_id, pg_conn, fabric_conn, batch_id)
        finally:
            fabric_conn.close()
    finally:
        pg_conn.close()

    return {"company_id": company_id, "batch_id": batch_id, **summary}


def run_full_sync(company_ids, sync_one, on_result=None):
    """
    Runs sync_one(company_id) for every id in company_ids, isolating failures
    so one company's error doesn't stop the rest of the run. Returns one
    result dict per company_id, each tagged with status "ok" or "error".

    If on_result is given, it's called after each company as
    on_result(companies_done, total_companies, result) -- e.g. to print a
    live progress line. It never affects run_full_sync's own return value.
    """
    results = []
    total = len(company_ids)
    for company_id in company_ids:
        try:
            summary = sync_one(company_id)
            result = {"company_id": company_id, "status": "ok", **summary}
        except Exception as exc:
            result = {"company_id": company_id, "status": "error", "error": str(exc)}
        results.append(result)
        if on_result is not None:
            on_result(len(results), total, result)
    return results


def sync_all_companies(on_result=None):
    """Syncs every company on the allowlist in a single run, sharing one
    batch_id and one pair of Fabric/Postgres connections across all of them."""
    batch_id = generate_batch_id()

    pg_conn = get_pg_connection()
    try:
        company_ids = fetch_all_company_ids(pg_conn)

        fabric_conn = get_fabric_connection()
        try:
            results = run_full_sync(
                company_ids,
                lambda company_id: sync_company_with_conns(company_id, pg_conn, fabric_conn, batch_id),
                on_result=on_result,
            )
        finally:
            fabric_conn.close()
    finally:
        pg_conn.close()

    return {"batch_id": batch_id, "results": results}


def make_progress_printer():
    """
    Returns an on_result callback for run_full_sync that prints a live,
    in-place "N/total companies synced (Xs elapsed)" line, timed from the
    moment the printer is created.
    """
    start = time.monotonic()

    def _print(companies_done, total_companies, result):
        elapsed = time.monotonic() - start
        status = "OK" if result["status"] == "ok" else "ERR"
        print(
            f"\r{companies_done}/{total_companies} companies synced "
            f"({elapsed:.0f}s elapsed, last: {status} company_id={result['company_id']})",
            end="",
            flush=True,
        )
        if companies_done == total_companies:
            print()

    return _print


def main():
    parser = argparse.ArgumentParser(description="Sync allowlisted companies' financials into bronze.")
    parser.add_argument(
        "company_id",
        type=int,
        nargs="?",
        default=None,
        help="Fabric investment_id / company_sync_list.company_id. Omit to sync every allowlisted company.",
    )
    args = parser.parse_args()

    if args.company_id is not None:
        summary = sync_company(args.company_id)
        print(f"Synced {summary['company_name']} (company_id={summary['company_id']}), batch {summary['batch_id']}")
        for table, count in summary["periods_synced"].items():
            print(f"  {table}: {count} period(s)")
        return

    run_start = time.monotonic()
    run_summary = sync_all_companies(on_result=make_progress_printer())
    total_elapsed = time.monotonic() - run_start

    results = run_summary["results"]
    ok = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] == "error"]

    print(f"Batch {run_summary['batch_id']}: synced {len(ok)}/{len(results)} companies in {total_elapsed:.1f}s")
    for r in ok:
        counts = ", ".join(f"{table}={count}" for table, count in r["periods_synced"].items())
        print(f"  OK  company_id={r['company_id']} {r['company_name']}: {counts}")
    for r in errors:
        print(f"  ERR company_id={r['company_id']}: {r['error']}")


if __name__ == "__main__":
    main()
