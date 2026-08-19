-- ============================================================================
-- Octane Traders — v3 update (run AFTER schema.sql and schema_update_v2.sql)
-- Adds the Aggressive Scalp strategy to the same signals table.
-- Idempotent — safe to re-run.
-- ============================================================================

-- 1) strategy column: 'smc' (swing) or 'scalp' (aggressive scalp)
alter table public.signals add column if not exists strategy text not null default 'smc';
create index if not exists signals_strategy_idx on public.signals (strategy);

-- 2) scalp signals have no SMC quality score -> allow null score
alter table public.signals alter column score drop not null;

-- 3) guard trigger (from v2) already lets the service_role write anything and
--    locks the browser to `resend` only — no change needed for strategy.
