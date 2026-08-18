-- ============================================================================
-- SMC Dashboard — v2 update (run this AFTER schema.sql)
-- Replaces schema_update_outcomes.sql. Idempotent — safe to re-run.
--
-- What this does:
--   1. Adds a `resend` flag so the dashboard can request a Telegram re-send.
--   2. Makes `status` READ-ONLY for everyone except the scanner (service role),
--      so outcomes are only ever set by the scanner's automatic TP/SL tracking.
--   3. Allows the browser (anon key) to change ONLY the `resend` flag.
-- ============================================================================

-- 1) resend flag
alter table public.signals add column if not exists resend boolean not null default false;

-- 2) trigger: service_role (the scanner) may update anything; everyone else
--    may change ONLY `resend`.
create or replace function public.signals_guard()
returns trigger
language plpgsql
as $$
declare
    role text := coalesce(auth.role(), 'anon');
begin
    if role = 'service_role' then
        return new;          -- trusted: the scanner's auto close-out etc.
    end if;

    if new.id          is distinct from old.id          then raise exception 'id immutable'; end if;
    if new.signal_key  is distinct from old.signal_key  then raise exception 'signal_key immutable'; end if;
    if new.pair        is distinct from old.pair        then raise exception 'pair immutable'; end if;
    if new.side        is distinct from old.side        then raise exception 'side immutable'; end if;
    if new.price       is distinct from old.price       then raise exception 'price immutable'; end if;
    if new.zone_lo     is distinct from old.zone_lo     then raise exception 'zone_lo immutable'; end if;
    if new.zone_hi     is distinct from old.zone_hi     then raise exception 'zone_hi immutable'; end if;
    if new.zone_type   is distinct from old.zone_type   then raise exception 'zone_type immutable'; end if;
    if new.sl          is distinct from old.sl          then raise exception 'sl immutable'; end if;
    if new.tp          is distinct from old.tp          then raise exception 'tp immutable'; end if;
    if new.pips_tp     is distinct from old.pips_tp     then raise exception 'pips_tp immutable'; end if;
    if new.pips_sl     is distinct from old.pips_sl     then raise exception 'pips_sl immutable'; end if;
    if new.rr          is distinct from old.rr          then raise exception 'rr immutable'; end if;
    if new.score       is distinct from old.score       then raise exception 'score immutable'; end if;
    if new.sweep_level is distinct from old.sweep_level then raise exception 'sweep_level immutable'; end if;
    if new.htf_bias    is distinct from old.htf_bias    then raise exception 'htf_bias immutable'; end if;
    if new.deal_pos    is distinct from old.deal_pos    then raise exception 'deal_pos immutable'; end if;
    if new.reasons     is distinct from old.reasons     then raise exception 'reasons immutable'; end if;
    if new.created_at  is distinct from old.created_at  then raise exception 'created_at immutable'; end if;
    if new.status      is distinct from old.status      then raise exception 'status immutable (auto-tracking only)'; end if;
    -- `resend` is intentionally NOT checked: the one editable column.
    return new;
end
$$;

-- replace any old trigger
drop trigger if exists signals_guard on public.signals;
drop trigger if exists signals_status_only on public.signals;
drop function if exists public.signals_status_only();
create trigger signals_guard
    before update on public.signals
    for each row
    execute function public.signals_guard();

-- 3) RLS: allow the anon/public key to attempt UPDATEs (the trigger above
--    restricts it to `resend` only)
drop policy if exists "public update status" on public.signals;
drop policy if exists "public update resend" on public.signals;
create policy "public update resend" on public.signals
    for update
    using (true)
    with check (true);
