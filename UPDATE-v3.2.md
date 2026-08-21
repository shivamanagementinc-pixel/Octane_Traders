# Octane Traders — Update v3.2 (three bug fixes)

This update fixes three bugs from v3.0. Do all four steps in order.

## The three bugs fixed

1. **Double orders** — the swing engine stacked a pending order on top of an
   embedded scalp position (no cross-engine dedup). Now: ONE position/order per
   symbol, across both engines.
2. **Wrong outcomes** — the GitHub swing scanner was closing out embedded scalp
   signals using Yahoo data (marking a real +178.52 win as "hit SL"). Now the
   scanner only manages its own swing signals, and the copier is the authority
   for scalp outcomes (uses real MT5 profit).
3. **Missing entry alerts in Telegram** — the Edge Function's 60-min cooldown
   was not strategy-aware, so a swing signal suppressed the scalp entry message
   (you only got the "hit SL"). Now swing and scalp never suppress each other.

---

## Step 1 — Supabase (2 things)

**1a. Fix the two wrong-status USDJPY trades** — SQL Editor → run the whole
contents of `supabase/fix_usdjpy_outcomes.sql` (marks the 07:35 USDJPY win as
hit_tp; the 06:40 loss stays hit_sl).

**1b. Update the Edge Function** (fixes the missing entry alerts):
1. Supabase → **Edge Functions → telegram-alert**
2. Replace the code with the contents of
   `supabase/functions/telegram-alert/index.ts` (from this zip)
3. **Save** (auto-deploys)

## Step 2 — GitHub (2 files)

Re-upload these two files to the repo (overwrite the old versions):

1. **`scanner.py`** — now only closes out its own `strategy='smc'` signals
2. **`copier/copier.py`** — v3.2 (cross-engine dedup + better SL/TP attach)

## Step 3 — Rebuild the exe

1. **Actions → Build Copier (Windows .exe) → Run workflow**
2. Download the artifact → replace `C:\octane\octane-copier.exe`
3. Run it → confirm the banner says **`v3.2`**

## Step 4 — Clean up the old test orders (optional)

If you still have the stray "market + pending" double orders from the earlier
bug sitting in MT5, close them manually (or use Admin → Close all) so they
don't skew your demo stats.

---

## After this update

- Each symbol gets **one** trade (never two).
- Scalp outcomes come from **real MT5 profit** → dashboard + Telegram correct.
- Telegram shows the **🎯 entry** for every new trade AND the **✅/❌ outcome**,
  for both swing and scalp, with no cross-suppression.

## Verify

- Next signal → Telegram: 🎯 entry message appears, then later ✅/❌ outcome.
- Dashboard → the 07:35 USDJPY now shows "hit tp" (after Step 1a).
- Console banner: `Octane Traders copier v3.2 started.`
