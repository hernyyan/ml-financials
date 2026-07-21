"""
Pure-function tests for the EAV -> wide-record pivot used by the #3 sync
script (scripts/bronze_sync.py). No Fabric/Postgres dependency -- per issue
#1's Testing Decisions, this covers a fully populated period, a partially
populated period, a period where a real item is 0, and a period missing
that same item entirely, asserting the two are never confused.
"""
from datetime import date

from scripts.bronze_sync import (
    DATA_ITEM_COLUMN_MAP,
    TABLE_COLUMNS,
    fetch_all_company_ids,
    pivot_periodic_rows,
    run_full_sync,
    upsert_records,
)

COMPANY_ID = 999001
COMPANY_NAME = "Test Co (fixture)"
PERIOD = date(2026, 3, 31)

# A few real IS data_item_ids for building test rows.
TOTAL_REVENUE_ID = 10717
COGS_ID = 10001
NET_INCOME_ID = 11683
EQUITY_CURE_ID = 12212


def test_data_item_column_map_covers_every_bronze_column():
    mapped_columns = {(table, col) for table, col in DATA_ITEM_COLUMN_MAP.values()}
    expected = {(table, col) for table, cols in TABLE_COLUMNS.items() for col in cols}
    assert mapped_columns == expected


def test_fully_populated_period_fills_every_income_statement_column():
    rows = [
        (data_item_id, PERIOD, 1.0)
        for data_item_id, (table, _) in DATA_ITEM_COLUMN_MAP.items()
        if table == "income_statement"
    ]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    record = result["income_statement"][0]
    for column in TABLE_COLUMNS["income_statement"]:
        assert record[column] == 1.0


def test_partially_populated_period_leaves_unsubmitted_columns_null():
    rows = [
        (TOTAL_REVENUE_ID, PERIOD, 1_000_000),
        (COGS_ID, PERIOD, 400_000),
    ]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    record = result["income_statement"][0]
    assert record["total_revenue"] == 1_000_000
    assert record["cogs"] == 400_000
    assert record["net_income"] is None
    assert record["equity_cure"] is None


def test_genuine_zero_is_preserved_not_coalesced_to_null():
    rows = [(NET_INCOME_ID, PERIOD, 0)]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    record = result["income_statement"][0]
    assert record["net_income"] == 0
    assert record["net_income"] is not None


def test_item_never_submitted_is_null_not_confused_with_zero():
    # net_income never appears in rows at all for this period.
    rows = [(TOTAL_REVENUE_ID, PERIOD, 500_000)]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    record = result["income_statement"][0]
    assert record["net_income"] is None
    assert record["total_revenue"] == 500_000


def test_records_carry_company_id_and_name():
    rows = [(TOTAL_REVENUE_ID, PERIOD, 1)]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    record = result["income_statement"][0]
    assert record["company_id"] == COMPANY_ID
    assert record["company_name"] == COMPANY_NAME
    assert record["period_end"] == PERIOD


def test_rows_grouped_into_separate_records_per_period():
    other_period = date(2026, 4, 30)
    rows = [
        (TOTAL_REVENUE_ID, PERIOD, 100),
        (TOTAL_REVENUE_ID, other_period, 200),
    ]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    records_by_period = {r["period_end"]: r for r in result["income_statement"]}
    assert records_by_period[PERIOD]["total_revenue"] == 100
    assert records_by_period[other_period]["total_revenue"] == 200


def test_rows_split_across_statements():
    cash_and_equivalents_id = 10016
    operating_cash_flow_id = 10047
    rows = [
        (TOTAL_REVENUE_ID, PERIOD, 1),
        (cash_and_equivalents_id, PERIOD, 2),
        (operating_cash_flow_id, PERIOD, 3),
    ]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    assert result["income_statement"][0]["total_revenue"] == 1
    assert result["balance_sheet"][0]["cash_and_equivalents"] == 2
    assert result["cash_flow"][0]["operating_cash_flow"] == 3


def test_unmapped_data_item_id_is_ignored():
    rows = [(TOTAL_REVENUE_ID, PERIOD, 1), (999_999_999, PERIOD, 1)]
    result = pivot_periodic_rows(rows, COMPANY_ID, COMPANY_NAME)
    assert result["income_statement"][0]["total_revenue"] == 1


def test_no_periodic_data_produces_no_records_for_any_table():
    # A company with zero periodic data available in Fabric must not be an
    # error -- it simply produces no bronze rows (issue #4 acceptance criteria).
    result = pivot_periodic_rows([], COMPANY_ID, COMPANY_NAME)
    assert result == {"income_statement": [], "balance_sheet": [], "cash_flow": []}


# -- run_full_sync: full-portfolio orchestration (issue #4) --------------


def test_run_full_sync_calls_sync_one_for_every_company_id():
    calls = []

    def sync_one(company_id):
        calls.append(company_id)
        return {"company_name": f"Co {company_id}", "periods_synced": {}}

    company_ids = [1, 2, 3]
    results = run_full_sync(company_ids, sync_one)

    assert calls == company_ids
    assert [r["company_id"] for r in results] == company_ids
    assert all(r["status"] == "ok" for r in results)


def test_run_full_sync_calls_on_result_once_per_company_with_running_count():
    def sync_one(company_id):
        return {"company_name": f"Co {company_id}", "periods_synced": {}}

    progress_calls = []
    run_full_sync([1, 2, 3], sync_one, on_result=lambda done, total, result: progress_calls.append((done, total)))

    assert progress_calls == [(1, 3), (2, 3), (3, 3)]


def test_run_full_sync_on_result_receives_the_result_just_produced():
    def sync_one(company_id):
        if company_id == 2:
            raise ValueError("boom")
        return {"company_name": f"Co {company_id}", "periods_synced": {}}

    seen_statuses = []
    run_full_sync([1, 2, 3], sync_one, on_result=lambda done, total, result: seen_statuses.append(result["status"]))

    assert seen_statuses == ["ok", "error", "ok"]


def test_run_full_sync_isolates_one_companys_failure_from_the_rest():
    def sync_one(company_id):
        if company_id == 2:
            raise ValueError("boom")
        return {"company_name": f"Co {company_id}", "periods_synced": {}}

    results = run_full_sync([1, 2, 3], sync_one)

    statuses = {r["company_id"]: r["status"] for r in results}
    assert statuses == {1: "ok", 2: "error", 3: "ok"}


def test_run_full_sync_records_error_message_for_failed_company():
    def sync_one(company_id):
        raise ValueError("company not on allowlist")

    results = run_full_sync([1], sync_one)

    assert results[0]["status"] == "error"
    assert results[0]["error"] == "company not on allowlist"


def test_run_full_sync_marks_zero_data_company_ok_not_error():
    # A company with no periodic data in Fabric produces zero periods per
    # table via pivot_periodic_rows/upsert_records, never an exception --
    # confirm that reaches run_full_sync as "ok", not "error" (issue #4 AC).
    def sync_one(company_id):
        return {"company_name": "Co", "periods_synced": {"income_statement": 0, "balance_sheet": 0, "cash_flow": 0}}

    results = run_full_sync([1], sync_one)
    assert results[0]["status"] == "ok"
    assert results[0]["periods_synced"] == {"income_statement": 0, "balance_sheet": 0, "cash_flow": 0}


# -- fetch_all_company_ids: real Postgres, rolled back after the test -----


def test_fetch_all_company_ids_includes_a_freshly_inserted_row(pg_conn):
    cur = pg_conn.cursor()
    cur.execute(
        "INSERT INTO public.company_sync_list (company_id, company_name) VALUES (%s, %s)",
        (COMPANY_ID, COMPANY_NAME),
    )
    ids = fetch_all_company_ids(pg_conn)
    assert COMPANY_ID in ids


def test_upsert_records_is_idempotent_at_full_scale(pg_conn):
    # Re-running the sync for the same (company_id, period_end) must update
    # the existing bronze row in place, never insert a duplicate (issue #4 AC).
    first_batch = [
        {
            "company_id": COMPANY_ID,
            "company_name": COMPANY_NAME,
            "period_end": PERIOD,
            "total_revenue": 100,
            **{col: None for col in TABLE_COLUMNS["income_statement"] if col != "total_revenue"},
        }
    ]
    second_batch = [{**first_batch[0], "total_revenue": 200}]

    upsert_records(pg_conn, "income_statement", first_batch, "batch_one")
    upsert_records(pg_conn, "income_statement", second_batch, "batch_two")

    cur = pg_conn.cursor()
    cur.execute(
        "SELECT total_revenue, source_batch_id FROM bronze.income_statement "
        "WHERE company_id = %s AND period_end = %s",
        (COMPANY_ID, PERIOD),
    )
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (200, "batch_two")
