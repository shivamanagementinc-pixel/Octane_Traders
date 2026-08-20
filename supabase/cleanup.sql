-- ============================================================================
-- Octane Traders — clean up test / demo data
-- Run this in the Supabase SQL Editor to remove all test artifacts and reset
-- the system to a clean "ready for real forward-testing" state.
--
-- Blocks:
--   1) turn OFF test mode
--   2) delete demo signals
--   3) delete all copier positions (they were test trades)
--   4) clear any pending close commands
--   5) OPTIONAL — full wipe of the signals table (fresh start)
-- ============================================================================

-- 1) turn OFF test mode (back to normal trading-hours rules)
update public.settings set value = 'false'::jsonb where key = 'test_mode';
-- (if the row doesn't exist yet, nothing happens — safe)

-- 2) delete demo signals
delete from public.signals where signal_key like 'demo-copier-test-%';

-- 3) delete all copier positions (test trades)
delete from public.positions;

-- 4) clear pending admin commands
delete from public.commands;

-- ============================================================================
-- OPTIONAL — full wipe: delete EVERYTHING in signals (both test AND any old
-- signals recorded while testing). Only run this if you want a 100% fresh
-- start. Otherwise keep it commented out.
-- ============================================================================
-- delete from public.signals;

-- ============================================================================
-- Verify (run after, expect "0 rows" for each):
--   select count(*) from public.signals  where signal_key like 'demo-copier-test-%';
--   select count(*) from public.positions;
--   select count(*) from public.commands;
--   select * from public.settings where key = 'test_mode';
-- ============================================================================
