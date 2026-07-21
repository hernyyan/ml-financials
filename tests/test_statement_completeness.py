"""
Fixture-based tests for public.statement_completeness (migrations/004,
005). Rows are inserted directly into warehouse and rolled back by the
pg_conn fixture -- no live Fabric data required.
"""
from datetime import date

TEST_COMPANY_ID = 999001
TEST_COMPANY_NAME = "Test Co (fixture)"
TEST_PERIOD_END = date(2026, 3, 31)

# warehouse table -> (view's statement_type label, line-item columns)
STATEMENT_TABLES = {
    "bronze_is": (
        "bronze_is",
        [
            "total_revenue", "cogs", "gross_profit", "total_operating_expenses",
            "ebitda_standard", "ebitda_adjustments", "adjusted_ebitda_standard",
            "depreciation_amortization", "interest_expense_income", "other_expense_income",
            "taxes", "net_income", "equity_cure", "adjusted_ebitda_including_cures",
            "covenant_ebitda",
        ],
    ),
    "bronze_bs": (
        "bronze_bs",
        [
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
    ),
    "bronze_cfs": (
        "bronze_cfs",
        ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "capex"],
    ),
}


def _insert_bronze_row(conn, table, **overrides):
    columns = STATEMENT_TABLES[table][1]
    row = {
        "company_id": TEST_COMPANY_ID,
        "company_name": TEST_COMPANY_NAME,
        "period_end": TEST_PERIOD_END,
        "source_system": "test_fixture",
        **{col: None for col in columns},
    }
    row.update(overrides)

    insert_columns = list(row)
    placeholders = ", ".join(f"%({c})s" for c in insert_columns)
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO warehouse.{table} ({", ".join(insert_columns)}, loaded_at)
        VALUES ({placeholders}, now())
        """,
        row,
    )


def _insert_bronze_is(conn, **overrides):
    _insert_bronze_row(conn, "bronze_is", **overrides)


def _completeness_row(conn, statement_type="bronze_is"):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT count_filled, count_total, is_empty
        FROM public.statement_completeness
        WHERE company_id = %s AND period_end = %s AND statement_type = %s
        """,
        (TEST_COMPANY_ID, TEST_PERIOD_END, statement_type),
    )
    return cur.fetchone()


def test_fully_filled_statement_has_full_count_and_is_not_empty(pg_conn):
    _insert_bronze_is(
        pg_conn,
        total_revenue=1_000_000,
        cogs=400_000,
        gross_profit=600_000,
        total_operating_expenses=200_000,
        ebitda_standard=400_000,
        ebitda_adjustments=10_000,
        adjusted_ebitda_standard=410_000,
        depreciation_amortization=50_000,
        interest_expense_income=20_000,
        other_expense_income=5_000,
        taxes=30_000,
        net_income=305_000,
        equity_cure=0,
        adjusted_ebitda_including_cures=410_000,
        covenant_ebitda=410_000,
    )
    count_filled, count_total, is_empty = _completeness_row(pg_conn)
    assert count_total == 15
    assert count_filled == 15
    assert is_empty is False


def test_partially_null_statement_reports_correct_count_filled(pg_conn):
    _insert_bronze_is(
        pg_conn,
        total_revenue=1_000_000,
        cogs=400_000,
        gross_profit=600_000,
        # everything else left NULL
    )
    count_filled, count_total, is_empty = _completeness_row(pg_conn)
    assert count_total == 15
    assert count_filled == 3
    assert is_empty is False


def test_all_zero_or_null_statement_is_flagged_empty_even_with_high_count_filled(pg_conn):
    _insert_bronze_is(
        pg_conn,
        total_revenue=0,
        cogs=0,
        gross_profit=0,
        total_operating_expenses=0,
        ebitda_standard=0,
        # remaining 10 columns left NULL
    )
    count_filled, count_total, is_empty = _completeness_row(pg_conn)
    assert count_total == 15
    assert count_filled == 5  # zeros count as filled, not missing
    assert is_empty is True


def test_genuine_zero_is_not_confused_with_missing(pg_conn):
    _insert_bronze_is(pg_conn, net_income=0)
    count_filled, _, _ = _completeness_row(pg_conn)
    assert count_filled == 1  # net_income=0 counts as filled, not missing


def test_genuine_nonzero_value_anywhere_marks_statement_not_empty(pg_conn):
    _insert_bronze_is(
        pg_conn,
        total_revenue=0,
        cogs=0,
        net_income=42,  # single genuine non-zero value
    )
    _, _, is_empty = _completeness_row(pg_conn)
    assert is_empty is False


def test_balance_sheet_branch_reports_correct_count_total_and_filled(pg_conn):
    _insert_bronze_row(
        pg_conn,
        "bronze_bs",
        cash_and_equivalents=500_000,
        accounts_receivable=100_000,
        total_assets=0,  # genuine zero, should count as filled
        # remaining 25 columns left NULL
    )
    count_filled, count_total, is_empty = _completeness_row(pg_conn, "bronze_bs")
    assert count_total == 28
    assert count_filled == 3
    assert is_empty is False


def test_balance_sheet_branch_flags_all_null_or_zero_as_empty(pg_conn):
    _insert_bronze_row(pg_conn, "bronze_bs", cash_and_equivalents=0, total_assets=0)
    count_filled, count_total, is_empty = _completeness_row(pg_conn, "bronze_bs")
    assert count_total == 28
    assert count_filled == 2  # zeros count as filled, not missing
    assert is_empty is True


def test_cash_flow_branch_reports_correct_count_total_and_filled(pg_conn):
    _insert_bronze_row(
        pg_conn,
        "bronze_cfs",
        operating_cash_flow=200_000,
        investing_cash_flow=-50_000,
        financing_cash_flow=0,  # genuine zero, should count as filled
        # capex left NULL
    )
    count_filled, count_total, is_empty = _completeness_row(pg_conn, "bronze_cfs")
    assert count_total == 4
    assert count_filled == 3
    assert is_empty is False


def test_cash_flow_branch_flags_all_null_or_zero_as_empty(pg_conn):
    _insert_bronze_row(pg_conn, "bronze_cfs", operating_cash_flow=0)
    count_filled, count_total, is_empty = _completeness_row(pg_conn, "bronze_cfs")
    assert count_total == 4
    assert count_filled == 1
    assert is_empty is True
