-- Issue #2: finalize company_id as INTEGER everywhere it appears, so joins
-- between bronze and public tables never require an implicit cast.
--
-- public.company_sync_list.company_id is already INTEGER (set by
-- 002_company_sync_list.sql); it is included below as a no-op for
-- documentation and idempotency.

ALTER TABLE bronze.income_statement
    ALTER COLUMN company_id TYPE INTEGER USING company_id::integer;

ALTER TABLE bronze.balance_sheet
    ALTER COLUMN company_id TYPE INTEGER USING company_id::integer;

ALTER TABLE bronze.cash_flow
    ALTER COLUMN company_id TYPE INTEGER USING company_id::integer;

ALTER TABLE public.companies
    ALTER COLUMN company_id TYPE INTEGER USING company_id::integer;

ALTER TABLE public.company_sync_list
    ALTER COLUMN company_id TYPE INTEGER USING company_id::integer;
