-- Issue #2: public.statement_completeness — one row per (company_id,
-- company_name, statement_type, period_end) present in bronze, with
-- count_filled/count_total for that statement and an is_empty flag.
--
-- count_filled: number of non-NULL line-item columns (a genuine 0 counts as
-- filled; only NULL is "missing").
-- count_total: fixed per statement type (15 / 28 / 4 confirmed line items).
-- is_empty: true only when every line-item column is NULL or 0 -- a
-- stricter signal than count_filled/count_total, meant to catch a
-- fully-populated-but-all-zero placeholder load.
--
-- Plain (non-materialized) view: bronze's data volume is small enough that
-- this never needs pre-computed results, and a view can't drift stale the
-- way a synced summary table could.

CREATE VIEW public.statement_completeness AS
SELECT
    b.company_id,
    b.company_name,
    'income_statement'::text AS statement_type,
    b.period_end,
    ((CASE WHEN total_revenue IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN cogs IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN gross_profit IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_operating_expenses IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN ebitda_standard IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN ebitda_adjustments IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN adjusted_ebitda_standard IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN depreciation_amortization IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN interest_expense_income IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_expense_income IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN taxes IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN net_income IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN equity_cure IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN adjusted_ebitda_including_cures IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN covenant_ebitda IS NOT NULL THEN 1 ELSE 0 END)) AS count_filled,
    15 AS count_total,
    ((total_revenue IS NULL OR total_revenue = 0)
        AND (cogs IS NULL OR cogs = 0)
        AND (gross_profit IS NULL OR gross_profit = 0)
        AND (total_operating_expenses IS NULL OR total_operating_expenses = 0)
        AND (ebitda_standard IS NULL OR ebitda_standard = 0)
        AND (ebitda_adjustments IS NULL OR ebitda_adjustments = 0)
        AND (adjusted_ebitda_standard IS NULL OR adjusted_ebitda_standard = 0)
        AND (depreciation_amortization IS NULL OR depreciation_amortization = 0)
        AND (interest_expense_income IS NULL OR interest_expense_income = 0)
        AND (other_expense_income IS NULL OR other_expense_income = 0)
        AND (taxes IS NULL OR taxes = 0)
        AND (net_income IS NULL OR net_income = 0)
        AND (equity_cure IS NULL OR equity_cure = 0)
        AND (adjusted_ebitda_including_cures IS NULL OR adjusted_ebitda_including_cures = 0)
        AND (covenant_ebitda IS NULL OR covenant_ebitda = 0)) AS is_empty
FROM bronze.income_statement b

UNION ALL

SELECT
    b.company_id,
    b.company_name,
    'balance_sheet'::text AS statement_type,
    b.period_end,
    ((CASE WHEN cash_and_equivalents IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN accounts_receivable IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN inventory IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN prepaid_expenses IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_current_assets IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_current_assets IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN property_plant_equipment IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN accumulated_depreciation IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN goodwill_intangibles IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_non_current_assets IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_non_current_assets IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_assets IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN accounts_payable IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN accrued_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN deferred_revenue IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN revolver_balance_sheet IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN current_maturities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_current_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_current_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN long_term_loans IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN long_term_leases IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_non_current_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_non_current_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_liabilities IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN paid_in_capital IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN retained_earnings IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN other_equity IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN total_equity IS NOT NULL THEN 1 ELSE 0 END)) AS count_filled,
    28 AS count_total,
    ((cash_and_equivalents IS NULL OR cash_and_equivalents = 0)
        AND (accounts_receivable IS NULL OR accounts_receivable = 0)
        AND (inventory IS NULL OR inventory = 0)
        AND (prepaid_expenses IS NULL OR prepaid_expenses = 0)
        AND (other_current_assets IS NULL OR other_current_assets = 0)
        AND (total_current_assets IS NULL OR total_current_assets = 0)
        AND (property_plant_equipment IS NULL OR property_plant_equipment = 0)
        AND (accumulated_depreciation IS NULL OR accumulated_depreciation = 0)
        AND (goodwill_intangibles IS NULL OR goodwill_intangibles = 0)
        AND (other_non_current_assets IS NULL OR other_non_current_assets = 0)
        AND (total_non_current_assets IS NULL OR total_non_current_assets = 0)
        AND (total_assets IS NULL OR total_assets = 0)
        AND (accounts_payable IS NULL OR accounts_payable = 0)
        AND (accrued_liabilities IS NULL OR accrued_liabilities = 0)
        AND (deferred_revenue IS NULL OR deferred_revenue = 0)
        AND (revolver_balance_sheet IS NULL OR revolver_balance_sheet = 0)
        AND (current_maturities IS NULL OR current_maturities = 0)
        AND (other_current_liabilities IS NULL OR other_current_liabilities = 0)
        AND (total_current_liabilities IS NULL OR total_current_liabilities = 0)
        AND (long_term_loans IS NULL OR long_term_loans = 0)
        AND (long_term_leases IS NULL OR long_term_leases = 0)
        AND (other_non_current_liabilities IS NULL OR other_non_current_liabilities = 0)
        AND (total_non_current_liabilities IS NULL OR total_non_current_liabilities = 0)
        AND (total_liabilities IS NULL OR total_liabilities = 0)
        AND (paid_in_capital IS NULL OR paid_in_capital = 0)
        AND (retained_earnings IS NULL OR retained_earnings = 0)
        AND (other_equity IS NULL OR other_equity = 0)
        AND (total_equity IS NULL OR total_equity = 0)) AS is_empty
FROM bronze.balance_sheet b

UNION ALL

SELECT
    b.company_id,
    b.company_name,
    'cash_flow_statement'::text AS statement_type,
    b.period_end,
    ((CASE WHEN operating_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN investing_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN financing_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN capex IS NOT NULL THEN 1 ELSE 0 END)) AS count_filled,
    4 AS count_total,
    ((operating_cash_flow IS NULL OR operating_cash_flow = 0)
        AND (investing_cash_flow IS NULL OR investing_cash_flow = 0)
        AND (financing_cash_flow IS NULL OR financing_cash_flow = 0)
        AND (capex IS NULL OR capex = 0)) AS is_empty
FROM bronze.cash_flow b;
