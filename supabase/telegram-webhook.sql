-- ============================================================================
-- Octane Traders — instant Telegram alerts (database trigger → Edge Function)
--
-- Run this ONCE in the Supabase SQL Editor AFTER deploying the Edge Function
-- (supabase/functions/telegram-alert). It fires the function the instant a
-- signal is INSERTed or UPDATEd — removing the 5-minute polling lag.
--
-- ⚠️ STEP 1 — replace YOUR-PROJECT-REF with your Supabase project ref:
--   Supabase Dashboard → Settings → General → "Reference ID" (e.g. abcdefghijklm)
-- ⚠️ STEP 2 — make sure the Edge Function is deployed with --no-verify-jwt
-- ============================================================================

-- 1) outbound HTTP from Postgres (if not already enabled)
create extension if not exists pg_net;

-- 2) the notifier: POST every new/updated signal row to the Edge Function
create or replace function public.octane_notify_telegram()
returns trigger
language plpgsql
as $$
begin
    perform net.http_post(
        url := 'https://YOUR-PROJECT-REF.supabase.co/functions/v1/telegram-alert',
        headers := jsonb_build_object('Content-Type', 'application/json'),
        body := jsonb_build_object(
            'type', TG_OP,
            'table', TG_TABLE_NAME,
            'record', row_to_json(new),
            'old_record', case when TG_OP = 'UPDATE' then row_to_json(old) else null end
        )
    );
    return new;
end;
$$;

-- 3) wire it to the signals table
drop trigger if exists octane_telegram_trigger on public.signals;
create trigger octane_telegram_trigger
after insert or update on public.signals
for each row execute function public.octane_notify_telegram();

-- ============================================================================
-- Alternative (no pg_net): use the dashboard instead —
--   Supabase Dashboard → Database → Webhooks → New webhook
--     Name: telegram-alert
--     Table: signals
--     Events: INSERT + UPDATE
--     URL:  https://YOUR-PROJECT-REF.supabase.co/functions/v1/telegram-alert
-- ============================================================================
