-- ============================================================================
-- SMC Signal Dashboard — Supabase schema
-- Run this once in the Supabase SQL Editor (Dashboard -> SQL -> New query).
-- ============================================================================

create table if not exists public.signals (
    id           bigint generated always as identity primary key,
    signal_key   text not null unique,                -- dedupe key from scanner
    pair         text not null,
    side         text not null check (side in ('LONG', 'SHORT')),
    price        numeric(18, 6) not null,
    zone_lo      numeric(18, 6) not null,
    zone_hi      numeric(18, 6) not null,
    zone_type    text,
    sl           numeric(18, 6) not null,
    tp           numeric(18, 6) not null,
    pips_tp      numeric(10, 2) not null,             -- potential (pips; $ for gold)
    pips_sl      numeric(10, 2) not null,
    rr           numeric(6, 2)  not null,
    score        integer        not null,             -- 0..100 quality
    sweep_level  numeric(18, 6),                      -- swept liquidity level
    htf_bias     text,
    deal_pos     numeric(6, 2),                       -- % position in dealing range
    reasons      jsonb          not null default '[]'::jsonb,
    status       text           not null default 'open'
                 check (status in ('open', 'hit_tp', 'hit_sl', 'expired')),
    created_at   timestamptz    not null default now()
);

create index if not exists signals_created_at_idx on public.signals (created_at desc);
create index if not exists signals_pair_idx       on public.signals (pair);
create index if not exists signals_score_idx      on public.signals (score desc);

-- ----------------------------------------------------------------------------
-- Security: dashboard reads with the public anon key; the scanner writes with
-- the service-role key. Never expose the service-role key in the browser.
-- ----------------------------------------------------------------------------
alter table public.signals enable row level security;

drop policy if exists "public read" on public.signals;
create policy "public read" on public.signals
    for select
    using (true);

-- ----------------------------------------------------------------------------
-- Realtime: broadcast new rows to subscribed dashboards
-- ----------------------------------------------------------------------------
do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public'
          and tablename = 'signals'
    ) then
        alter publication supabase_realtime add table public.signals;
    end if;
end $$;

-- ----------------------------------------------------------------------------
-- Optional: handy view for stats
-- ----------------------------------------------------------------------------
create or replace view public.signal_stats as
select
    count(*)                                        as total,
    count(*) filter (where score >= 80)             as high_quality,
    count(*) filter (where status = 'open')         as open_count,
    count(*) filter (where status = 'hit_tp')       as wins,
    count(*) filter (where status = 'hit_sl')       as losses,
    round(avg(score), 1)                            as avg_score
from public.signals;
