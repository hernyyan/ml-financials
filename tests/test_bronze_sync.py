"""
Pure-function tests for the EAV -> wide-record pivot used by the #3 sync
script (scripts/bronze_sync.py). No Fabric/Postgres dependency -- per issue
#1's Testing Decisions, this covers a fully populated period, a partially
populated period, a period where a real item is 0, and a period missing
that same item entirely, asserting the two are never confused.
"""
from datetime import date

from scripts.bronze_sync import DATA_ITEM_COLUMN_MAP, TABLE_COLUMNS, pivot_periodic_rows

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
