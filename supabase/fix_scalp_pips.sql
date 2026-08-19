-- ============================================================================
-- Octane Traders — repair scalp "0 pip" values in existing rows
--
-- Bug fixed in the scanner: scalp signals were stored with pips in raw price
-- units (e.g. 0.00044), which the numeric(10,2) column rounded to 0.00.
-- This recomputes pips_tp / pips_sl from the stored price/sl/tp for existing
-- scalp rows. Run once in the Supabase SQL Editor.
-- ============================================================================

update public.signals
set
  pips_tp = round(
    abs(tp - price) /
    case
      when pair like '%JPY%'                  then 0.01
      when pair in ('SPX500','NAS100','US30') then 1.0
      else 0.0001
    end, 1),
  pips_sl = round(
    abs(price - sl) /
    case
      when pair like '%JPY%'                  then 0.01
      when pair in ('SPX500','NAS100','US30') then 1.0
      else 0.0001
    end, 1)
where strategy = 'scalp'
  and (pips_tp = 0 or pips_tp is null);
