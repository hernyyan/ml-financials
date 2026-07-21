-- Issue #5 (see .scratch/warehouse-schema-rename/PRD.md): collapse the
-- bronze/silver/gold medallion layers from three separate Postgres schemas
-- into one `warehouse` schema, where bronze/silver/gold becomes a naming
-- convention (bronze_/silver_/gold_ table prefixes) rather than a physical
-- schema boundary. silver and gold are dropped -- both are confirmed empty,
-- with no calculated metrics ever having been built into them.
--
-- Forward-only, no rollback script, consistent with 003/004 precedent: this
-- is a cosmetic/organizational rename over already-tested, unchanged logic,
-- not new behavior.
--
-- Safety: the DROP SCHEMA calls below use the non-cascading form and are
-- preceded by an explicit emptiness check, so the migration fails loudly
-- instead of silently deleting anything unexpected in silver/gold.

DO $$
DECLARE
    silver_object_count INTEGER;
    gold_object_count INTEGER;
BEGIN
    SELECT count(*) INTO silver_object_count
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'silver';

    SELECT count(*) INTO gold_object_count
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'gold';

    IF silver_object_count > 0 THEN
        RAISE EXCEPTION 'silver schema is not empty (% objects found) -- aborting migration', silver_object_count;
    END IF;

    IF gold_object_count > 0 THEN
        RAISE EXCEPTION 'gold schema is not empty (% objects found) -- aborting migration', gold_object_count;
    END IF;
END $$;

-- Schema: bronze -> warehouse. Existing privileges are tied to the schema's
-- OID, not its name, so this preserves all existing grants automatically.
ALTER SCHEMA bronze RENAME TO warehouse;

-- Tables: adopt the bronze_is/bronze_bs/bronze_cfs naming convention.
ALTER TABLE warehouse.income_statement RENAME TO bronze_is;
ALTER TABLE warehouse.balance_sheet RENAME TO bronze_bs;
ALTER TABLE warehouse.cash_flow RENAME TO bronze_cfs;

-- Constraints and indexes: renamed to match, per the pg_constraint/pg_indexes
-- introspection recorded in the PRD (the original 001_bronze_schema.sql
-- migration that created these was never committed to this repo).
ALTER TABLE warehouse.bronze_is RENAME CONSTRAINT income_statement_pkey TO bronze_is_pkey;
ALTER TABLE warehouse.bronze_is RENAME CONSTRAINT uq_bronze_income_stmt TO uq_bronze_is;
ALTER INDEX warehouse.idx_bronze_income_period RENAME TO idx_bronze_is_period;
ALTER INDEX warehouse.idx_bronze_income_company_period RENAME TO idx_bronze_is_company_period;

ALTER TABLE warehouse.bronze_bs RENAME CONSTRAINT balance_sheet_pkey TO bronze_bs_pkey;
ALTER TABLE warehouse.bronze_bs RENAME CONSTRAINT uq_bronze_balance_sheet TO uq_bronze_bs;
ALTER INDEX warehouse.idx_bronze_balance_period RENAME TO idx_bronze_bs_period;
ALTER INDEX warehouse.idx_bronze_balance_company_period RENAME TO idx_bronze_bs_company_period;

ALTER TABLE warehouse.bronze_cfs RENAME CONSTRAINT cash_flow_pkey TO bronze_cfs_pkey;
ALTER TABLE warehouse.bronze_cfs RENAME CONSTRAINT uq_bronze_cash_flow TO uq_bronze_cfs;
ALTER INDEX warehouse.idx_bronze_cashflow_period RENAME TO idx_bronze_cfs_period;
ALTER INDEX warehouse.idx_bronze_cashflow_company_period RENAME TO idx_bronze_cfs_company_period;

-- silver/gold: confirmed empty above; plain DROP SCHEMA (no CASCADE) so this
-- still fails loudly if an object slips in between the check and the drop.
DROP SCHEMA silver;
DROP SCHEMA gold;

-- public.statement_completeness: same column list/types, only the FROM
-- clause's table references and the statement_type literals change.
CREATE OR REPLACE VIEW public.statement_completeness AS
SELECT
    b.company_id,
    b.company_name,
    'bronze_is'::text AS statement_type,
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
FROM warehouse.bronze_is b

UNION ALL

SELECT
    b.company_id,
    b.company_name,
    'bronze_bs'::text AS statement_type,
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
FROM warehouse.bronze_bs b

UNION ALL

SELECT
    b.company_id,
    b.company_name,
    'bronze_cfs'::text AS statement_type,
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
FROM warehouse.bronze_cfs b;
