-- ============================================================================
-- Octane Traders — Stage 1: multi-account auto-trading (run AFTER v2 + v3)
--
-- Adds:
--   accounts             — per-account config (risk %, active toggle)
--   account_credentials  — MT5 login/password/server (secret: insert-only)
--   settings             — master kill-switch
--   positions            — copier writes each trade here
--   commands             — admin → copier (close position / close all)
--
-- SECURITY NOTE (Stage 1 = demo accounts):
--   The anon/publishable key may read account config and issue close commands.
--   MT5 passwords live in account_credentials with an INSERT-ONLY policy for
--   anon (it can store a password but never read it back); only the copier's
--   service-role key can read them. For Stage 2 (live subscribers) add
--   Supabase Auth + an admin Edge Function so nothing sensitive touches the
--   browser at all.
-- ============================================================================

-- 1) accounts (non-secret config)
create table if not exists public.accounts (
    id          bigint generated always as identity primary key,
    name        text not null,
    broker      text,
    is_demo     boolean not null default true,
    risk_pct    numeric(6,3) not null default 0.5,
    active      boolean not null default true,
    created_at  timestamptz not null default now()
);

-- 2) account_credentials (secret — anon can INSERT but never SELECT)
create table if not exists public.account_credentials (
    id            bigint generated always as identity primary key,
    account_id    bigint not null references public.accounts(id) on delete cascade,
    mt5_login     text not null,
    mt5_password  text not null,
    mt5_server    text,
    symbol_suffix text not null default '',   -- e.g. ".a" for some brokers
    created_at    timestamptz not null default now()
);

-- 3) settings (master kill-switch)
create table if not exists public.settings (
    key        text primary key,
    value      jsonb not null,
    updated_at timestamptz not null default now()
);

insert into public.settings (key, value) values ('trade_enabled', 'true'::jsonb)
on conflict (key) do nothing;

-- 4) positions (copier writes, admin reads)
create table if not exists public.positions (
    id          bigint generated always as identity primary key,
    account_id  bigint not null references public.accounts(id) on delete cascade,
    signal_id   bigint,
    ticket      bigint,
    pair        text not null,
    side        text not null,
    volume      numeric(12,4) not null,
    open_price  numeric(18,5),
    sl          numeric(18,5),
    tp          numeric(18,5),
    status      text not null default 'open',  -- open | closed_win | closed_loss | closed_manual
    opened_at   timestamptz not null default now(),
    closed_at   timestamptz
);

create index if not exists positions_status_idx on public.positions (status);
create index if not exists positions_account_idx on public.positions (account_id);

-- 5) commands (admin → copier)
create table if not exists public.commands (
    id          bigint generated always as identity primary key,
    account_id  bigint,                        -- null = all accounts
    action      text not null,                 -- close_position | close_all
    ticket      bigint,
    status      text not null default 'pending', -- pending | done
    created_at  timestamptz not null default now()
);

create index if not exists commands_status_idx on public.commands (status);

-- ----------------------------------------------------------------------------
-- Row Level Security (anon = publishable key, service_role bypasses everything)
-- ----------------------------------------------------------------------------
alter table public.accounts            enable row level security;
alter table public.account_credentials enable row level security;
alter table public.settings            enable row level security;
alter table public.positions           enable row level security;
alter table public.commands            enable row level security;

-- accounts: anon can read + manage config (demo-stage convenience)
drop policy if exists "anon read accounts" on public.accounts;
create policy "anon read accounts" on public.accounts for select using (true);
drop policy if exists "anon insert accounts" on public.accounts;
create policy "anon insert accounts" on public.accounts for insert with check (true);
drop policy if exists "anon update accounts" on public.accounts;
create policy "anon update accounts" on public.accounts for update using (true) with check (true);
drop policy if exists "anon delete accounts" on public.accounts;
create policy "anon delete accounts" on public.accounts for delete using (true);

-- credentials: anon can INSERT (store a password) but never SELECT/UPDATE
drop policy if exists "anon insert creds" on public.account_credentials;
create policy "anon insert creds" on public.account_credentials
    for insert with check (true);
-- (no SELECT policy → anon can never read passwords back)

-- settings: anon can read + toggle the kill-switch
drop policy if exists "anon read settings" on public.settings;
create policy "anon read settings" on public.settings for select using (true);
drop policy if exists "anon update settings" on public.settings;
create policy "anon update settings" on public.settings for update using (true) with check (true);

-- positions: anon read-only (copier writes via service_role)
drop policy if exists "anon read positions" on public.positions;
create policy "anon read positions" on public.positions for select using (true);

-- commands: anon can create + read (close requests)
drop policy if exists "anon read commands" on public.commands;
create policy "anon read commands" on public.commands for select using (true);
drop policy if exists "anon insert commands" on public.commands;
create policy "anon insert commands" on public.commands for insert with check (true);
