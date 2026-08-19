# ⚡ Octane Traders — Installation Guide

Complete, step-by-step setup. **Total time: ~30–45 minutes.** Everything is free.

> **TL;DR order:** ① Supabase (database) → ② GitHub (scanner) → ③ Netlify (dashboard) → ④ Telegram (alerts).

---

## 0. What you're building

```
GitHub Actions  ──runs scanner.py every 5 min──▶  finds SMC setups
       │
       │ POST (service-role key)
       ▼
Supabase (Postgres)  ──stores signals──▶  auto-tracks TP/SL outcomes
       │
       │ SELECT + Realtime (anon key)
       ▼
Netlify dashboard  ──shows signals, equity curve, performance report──▶  Telegram alerts 🚨
```

The scanner runs on **GitHub's servers** (free), the data lives in **Supabase**
(free), the dashboard is a **static site on Netlify** (free). Nothing runs on
your computer.

---

## 1. Supabase — the database (~5 min)

1. Go to [supabase.com](https://supabase.com) → sign up → **New project**
   - Any name (e.g. `octane-traders`), any region, set a database password
   - Wait ~1 min for provisioning
2. **SQL Editor → New query**
3. Paste the **entire contents of `supabase/schema.sql`** → **Run**
   - Creates the `signals` table + security rules + realtime
4. Paste the **entire contents of `supabase/schema_update_v2.sql`** → **Run**
   - Adds the resend flag + locks `status` to auto-tracking only
5. **Project Settings → API** — copy these 3 values (you'll need them twice):

| Value | Use | Secret? |
|---|---|---|
| **Project URL** (`https://xyz.supabase.co`) | GitHub + dashboard | no |
| **`anon` / publishable key** | dashboard (browser) | safe to expose |
| **`service_role` / secret key** | GitHub (scanner) | ⚠️ SECRET |

> **Which key is which?** New dashboards label them `publishable` (= anon, for
> the browser) and `secret` (= service_role, for the scanner). Old dashboards
> label them `anon` and `service_role`.

---

## 2. GitHub — the scanner (~10 min)

### 2a. Create the repo

1. [github.com](https://github.com) → **New repository** → name it `octane-traders`
   - Visibility: **public** = unlimited free Action minutes (recommended)
   - Don't add a README yet
2. **Upload the files.** Easiest: unzip this folder, then on the repo page
   click **Add file → Upload files** and drag in the *contents* (so
   `scanner.py`, `.github/`, `dashboard/`, `supabase/`, `docs/`, `research/`
   land at the repo root).

   > ⚠️ **Hidden files:** macOS/Windows hide folders that start with a dot —
   > that's `.github` and `.gitignore`. If they don't appear after uploading,
   > create them in GitHub's editor instead: **Add file → Create new file**,
   > type the path `.github/workflows/scan.yml`, paste the file's contents,
   > commit. Do the same for `telegram-test.yml` and `demo-signal.yml`.

3. Verify on the **Code** tab: you should see `.github/`, `scanner.py`,
   `research/`, `dashboard/`, `supabase/`, `docs/` all at the top level.

### 2b. (v3 only) Add the scalp strategy column

The Aggressive Scalp engine writes to the same `signals` table, tagged with
`strategy = 'scalp'`. After running the two SQL files in step 1, run this one
more in the **Supabase SQL Editor**:

```
paste the contents of supabase/schema_update_v3.sql → Run
```

(It adds a `strategy` column and lets scalp signals have no SMC score.)

### 2c. Add secrets (connects the repo to Supabase + Telegram)

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `SUPABASE_URL` | your Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | the **service_role / secret** key |
| `TELEGRAM_BOT_TOKEN` | from step 4 (add after you create the bot) |
| `TELEGRAM_CHAT_ID` | from step 4 |

> ⚠️ Must be under **"Repository secrets"** — NOT "Environment secrets".

### 2d. Turn it on

1. **Actions tab → SMC Scan → Enable workflow** (and **Scalp Scan** if you want
   the aggressive strategy too — GitHub disables scheduled workflows until
   enabled)
2. **Run workflow → Run workflow** (first manual run on each)
3. Open the run → **"Run SMC scanner"** step → watch the log:
   - `[supabase: ok]` = signal saved ✅
   - `no qualifying setups right now` = working, just nothing passed the filters ✅
   - `[session] skipping` = outside 03:00–17:00 ET (normal at night) ✅
   - `[blackout] skipping` = inside 17:00–18:30 ET (normal) ✅

Both strategies now run **every 5 minutes** automatically:
- `SMC Scan` → swing signals (SMC, 15m)
- `Scalp Scan` → aggressive scalp signals (5m momentum, 1R targets)

---

## 3. Netlify — the dashboard (~5 min)

1. [app.netlify.com](https://app.netlify.com) → **Add new site → Import from Git → GitHub**
   - Pick the `octane-traders` repo
   - **Base directory** = `dashboard` (publish dir `.` is already configured)
   - Deploy
2. Open your site URL (e.g. `https://something.netlify.app`)
3. Click **Connect Supabase** (top-right) → paste:
   - **Project URL**
   - **anon / publishable key** (NOT the service_role key)
4. Badge flips from orange **DEMO DATA** to green **LIVE** — real signals stream in.

> Dashboard runs in demo mode (with sample + backtest data) until you connect
> Supabase — that's useful for previewing.

---

## 4. Telegram — alerts (~5 min)

1. Open Telegram → search **@BotFather** → `/newbot` → name it (e.g. "Octane Traders Alerts")
   → copy the **bot token**
2. Open a chat with your new bot and send any message (e.g. `hi`)
3. Get your **chat id**: in a browser open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   → find `"chat":{"id":123456789,...}` → that number is your chat id
4. Add the two secrets to GitHub (from step 2b): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
5. Test it: **Actions → Telegram Test → Run workflow** → you get a message in ~30s
6. Test a signal format: **Actions → Demo Signal → Run workflow**

Now you'll get: 🚨 on every new signal, ✅/❌ on every TP/SL hit.

---

## 5. Verify the whole loop (1 min)

1. Dashboard open → green LIVE badge, signals visible
2. **Actions → SMC Scan → Run workflow**
3. Watch the log → `[supabase: ok]` → check the dashboard updates **live**
   (no refresh needed — Supabase Realtime)

---

## 6. How it behaves day-to-day

| Time (ET) | What happens |
|---|---|
| 03:00–17:00 | Scans every 5 min, finds + alerts signals (London/NY hours) |
| 17:00–18:30 | **Blackout** — silent (rollover spread spike, no fake signals) |
| 18:30–03:00 | **Session off** — silent (Asian chop / late drift filtered out) |
| Weekends | Markets closed — scanner finds nothing, stays idle |

So expect **~2.5 quality signals/day**, clustered in London/NY hours.

---

## 7. Configuration reference

All knobs are CLI flags on `scanner.py` (edit them in `.github/workflows/scan.yml`):

| Flag | Default | What it does |
|---|---|---|
| `--min-score` | 70 | minimum quality |
| `--max-score` | 89 | ceiling (90+ = losing "chase zone") |
| `--min-pips` | 20 | minimum TP distance |
| `--telegram-cooldown-hours` | 1 | min hours between pings per pair+side |
| `--session-start/--session-end` | 03:00 / 17:00 | active hours (ET) |
| `--session-tz` | America/Toronto | timezone (DST-aware) |
| `--no-session-filter` | off | scan 24/5 instead |
| `--blackout-start/--blackout-end` | 17:00 / 18:30 | rollover silence window |
| `--no-blackout` | off | disable blackout |
| `--no-bias-filter` | off | allow counter-trend signals |
| `--pairs` | 4 defaults | override the universe |

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard shows "DEMO DATA" | Click **Connect Supabase** and paste URL + anon key |
| Table empty after scanning | Check the Actions log for `[supabase: ok]` vs an error |
| `[supabase: http 401/403]` | Wrong service_role key (you pasted the anon/publishable key) |
| `[supabase: http 404]` | `schema.sql` not run — run both SQL files in Supabase |
| `[supabase: skip]` | Secrets not in **Repository** secrets, or `scan.yml` is old |
| `[telegram: err 401]` | Wrong bot token |
| No Telegram messages but dashboard updates | Alerts only fire on *new* signals — use the 📤 resend button, or check the cooldown |
| Workflow missing from Actions tab | `.github/` folder not at repo root (hidden-file issue — see 2a) |
| `unrecognized arguments` in log | `scanner.py` on GitHub is the old version — re-upload it |

---

## 9. File reference

| Path | What |
|---|---|
| `scanner.py` | Swing engine: SMC detection, filters, Supabase push, Telegram, auto close-out |
| `research/scalp_engine.py` | Scalp engine: 5m momentum pullbacks, 1R/1.5R targets |
| `.github/workflows/scan.yml` | Scheduled 5-min swing scan |
| `.github/workflows/scalp-scan.yml` | Scheduled 5-min scalp scan |
| `.github/workflows/telegram-test.yml` | One-click Telegram test |
| `.github/workflows/demo-signal.yml` | One-click demo signal |
| `supabase/schema.sql` | Table + indexes + RLS + realtime |
| `supabase/schema_update_v2.sql` | Resend flag + status lock |
| `supabase/schema_update_v3.sql` | `strategy` column (swing vs scalp) + nullable score |
| `dashboard/` | Static dashboard (Netlify) — Swing + Scalp tabs |
| `dashboard/backtest-data.js` | Swing walk-forward trades (shown in the history table) |
| `dashboard/scalp-backtest-data.js` | Scalp walk-forward trades (1R, shown in the history table) |
| `docs/backtest-report.html` | Full research report (open in browser, print to PDF) |
| `research/pairs_engine.py` | Experimental pairs-trading engine (rejected, kept for reference) |

---

## 10. Security notes

- The **service_role key** bypasses all security rules — it lives ONLY as a
  GitHub Actions secret, injected at runtime. Never put it in the browser.
- The **anon key** can only read (see RLS in `schema.sql`) — safe to ship.
- The dashboard is fully static — no server code, no Netlify Functions.
- The scanner is stdlib-only Python — zero third-party dependencies.

---

## License & disclaimer

This is trading software for **educational purposes**. Historical backtests are
not guarantees of future results. Crypto/FX trading involves substantial risk
of loss. Always forward-test on a demo account before risking real capital.
