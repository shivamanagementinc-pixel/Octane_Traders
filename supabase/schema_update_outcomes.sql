-- ============================================================================
-- SMC Dashboard — outcome marking (run this AFTER the original schema.sql)
--
-- Lets the dashboard (anon/publishable key) flip a signal's status to
-- hit_tp / hit_sl / expired, so you can build a performance report.
-- A trigger hard-blocks changes to ANY column other than `status`.
-- ============================================================================

-- 1) allow UPDATEs from the public/anon role
create policy "public update status" on public.signals
    for update
    using (true)
    with check (true);

-- 2) block any change to columns other than `status`
create or replace function public.signals_status_only()
returns trigger
language plpgsql
as $$
begin
    if new.id          is distinct from old.id          then raise exception 'id is immutable'; end if;
    if new.signal_key  is distinct from old.signal_key  then raise exception 'signal_key is immutable'; end if;
    if new.pair        is distinct from old.pair        then raise exception 'pair is immutable'; end if;
    if new.side        is distinct from old.side        then raise exception 'side is immutable'; end if;
    if new.price       is distinct from old.price       then raise exception 'price is immutable'; end if;
    if new.zone_lo     is distinct from old.zone_lo     then raise exception 'zone_lo is immutable'; end if;
    if new.zone_hi     is distinct from old.zone_hi     then raise exception 'zone_hi is immutable'; end if;
    if new.zone_type   is distinct from old.zone_type   then raise exception 'zone_type is immutable'; end if;
    if new.sl          is distinct from old.sl          then raise exception 'sl is immutable'; end if;
    if new.tp          is distinct from old.tp          then raise exception 'tp is immutable'; end if;
    if new.pips_tp     is distinct from old.pips_tp     then raise exception 'pips_tp is immutable'; end if;
    if new.pips_sl     is distinct from old.pips_sl     then raise exception 'pips_sl is immutable'; end if;
    if new.rr          is distinct from old.rr          then raise exception 'rr is immutable'; end if;
    if new.score       is distinct from old.score       then raise exception 'score is immutable'; end if;
    if new.sweep_level is distinct from old.sweep_level then raise exception 'sweep_level is immutable'; end if;
    if new.htf_bias    is distinct from old.htf_bias    then raise exception 'htf_bias is immutable'; end if;
    if new.deal_pos    is distinct from old.deal_pos    then raise exception 'deal_pos is immutable'; end if;
    if new.reasons     is distinct from old.reasons     then raise exception 'reasons is immutable'; end if;
    if new.created_at  is distinct from old.created_at  then raise exception 'created_at is immutable'; end if;
    return new;
end
$$;

drop trigger if exists signals_status_only on public.signals;
create trigger signals_status_only
    before update on public.signals
    for each row
    execute function public.signals_status_only();
