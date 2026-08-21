-- ============================================================================
-- Octane Traders — fix the two USDJPY trades that showed the wrong outcome
-- (the 07:35 scalp was a +178.52 WIN in MT5 but the dashboard/Telegram said
--  hit_sl because the old swing scanner wrongly closed it out).
--
-- Run ONCE in the Supabase SQL Editor. Then the dashboard + any re-sent
-- Telegram message will show the correct outcome.
-- ============================================================================

begin;
alter table public.signals disable trigger signals_guard;

-- 07:35 USDJPY SHORT (entry ~158.656) was a WIN in MT5 (+178.52) -> hit_tp
update public.signals set status = 'hit_tp'
where pair = 'USDJPY' and side = 'SHORT' and round(price, 3) = 158.656;

-- (the 06:40 USDJPY SHORT @ ~158.579 really was a loss -> leave as hit_sl)

alter table public.signals enable trigger signals_guard;
commit;

-- verify:
-- select pair, side, price, status from public.signals
--   where pair='USDJPY' and side='SHORT'
--   order by created_at desc limit 5;
