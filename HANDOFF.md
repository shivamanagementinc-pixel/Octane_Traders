# Octane Traders — Complete Project Handoff

> **Purpose:** paste this entire document into a new chat (or share with anyone)
> to bring them up to speed on what we built, how it works, and where we're going.

---

## 1. What Octane Traders is

An automated trading system for **forex + gold + index CFDs**, built in four layers:

1. **Signal scanners** (Python, run on GitHub Actions — free, scheduled every 5 min)
2. **Supabase** (Postgres database — stores signals, accounts, positions, settings)
3. **Copier** (Python, compiled to a Windows `.exe`, runs on my PC 24/7, talks to MT5)
4. **Dashboard + Admin** (static site on Netlify — signal history, equity curve, account management)

Plus **instant Telegram alerts** via a Supabase Edge Function.

### The full flow

```
GitHub Actions (every 5 min)
   ├─ Swing scanner  (SMC + liquidity, 15m/1h)  → signals table
   └─ Scalp scanner  (5m momentum pullback)      → signals table
            │
            ▼
      Supabase (Postgres + Realtime)
            │
            ├─────────────▶ Netlify dashboard (live, no refresh)
            ├─────────────▶ Edge Function → Telegram (instant alerts)
            │
            ▼
      Copier (.exe on my PC, every 15s)
        ├─ reads new signals + accounts + kill-switch
        ├─ sizes lots per account (risk% × balance ÷ stop distance)
        ├─ places orders on MT5 (market or pending)
        └─ reconciles positions + processes admin commands
```

---

## 2. What we built (chronological summary)

### Phase 1 — Research & data
- Researched BloFin (crypto), then switched to **forex** (TradeSway first, then my own 1:200 account).
- Settled on **MT5** as the broker platform (broker: **Upcomers**, server `Upcomers-Server`).

### Phase 2 — Signal scanners (the "brain", v1)
- Built a **Python SMC + liquidity scanner** (stdlib-only, no dependencies):
  - Swing highs/lows, equal highs/lows (liquidity pools)
  - Liquidity sweeps (stop-hunt wick + reclaim)
  - Order Blocks (OB) and Fair Value Gaps (FVG)
  - Premium/discount, 1H trend bias
  - Quality score 0–100
- Added a **scalp engine** (5m momentum pullback, RSI + 15m trend, 1×ATR stop).

### Phase 3 — Backtesting & honest filtering (the most important part)
Ran **walk-forward backtests with train/test splits**. Key findings:
- Raw 9-pair "score ≥70" = **92 signals/day, 24.6% win, −0.03R (losing)**
- Narrow to 4 pairs + score 70–89 = **+0.19R**
- Add bias alignment (trade WITH trend) = **+0.41R**
- Add London/NY session filter = **~2.5 signals/day, 40.3% win, +0.62R/trade**
- The "90+ score" bucket actually **lost** money (−0.12R) → hard-capped at 89.
- Discovered persistent (re-fired) setups win **50% vs 29%** → record everything, cooldown alerts only.
- Scalp engine (1.5R target + min 5 pips FX / 30 pts index) = **62% win, ~+0.43R/trade net**.
- Rejected a **pairs cointegration** strategy after honest backtesting showed −0.43R.

### Phase 4 — Infrastructure
- **Supabase**: `signals` table (+ `strategy`, `resend` columns), RLS, Realtime.
- **Netlify dashboard**: two tabs (Swing / Aggressive Scalp), filters, equity curve,
  performance report (win rate, expectancy, profit factor, per-pair), CSV export,
  backtest history embedded as rows.
- **Telegram Edge Function** (Deno/TS): instant alerts on new signal / resend / TP-SL,
  "🔄 RESEND" header on resends, outcome labels (HIT TP / HIT SL / EXPIRED).
- **Blackout + session filters**: no new signals during 17:00–18:30 ET (rollover)
  or outside 03:00–17:00 ET (London/NY only).

### Phase 5 — Trade copier (the "hands", Stage 1)
- `copier.py` + `lot_calculator.py` + `config.py` (broker symbol/pip-value mapping).
- **Risk sizing**: `lots = (balance × risk% ) ÷ (stop × pip-value)`, rounded **DOWN**
  to 0.01 step (0.1354 → 0.13), min 0.01, default **0.5% risk per trade**.
- **Admin page** (`admin.html`): master kill-switch, add/remove accounts, per-account
  risk %, open positions, close / close-all, **wins-today counter**.
- **Compiled to a Windows .exe** via GitHub Actions (no Python needed on the target PC).

### Phase 6 — Broker-specific bug fixes (Upcomers)
These were painful but instructive. Upcomers:
1. **No FOK filling** → auto-detect + try FOK → IOC → RETURN.
2. **"Invalid stops" on market orders with SL/TP** → fallback: bare IOC order,
   then attach SL/TP via `TRADE_ACTION_SLTP`.
3. **Rejects `expiration` on pending orders** → fallback to GTC limit, copier
   enforces its own 30-min expiry.
4. **CFD symbols use `.c` suffix** → `SPCUSD.c`, `NACUSD.c`, `DJCUSD.c`.
5. FX pairs are plain (`EURUSD`), gold is `XAUUSD`.

### Phase 7 — Safety hardening (very important)
- **Price-sanity guard**: skip any signal whose price diverges >0.3% (FX) / 0.5%
  (gold/indices) from the broker's live quote.
- **Stale-signal sweep**: never trade signals older than 10 min; mark >60-min-old
  open signals "expired".
- **No naked positions**: if SL/TP attach fails, auto-close the bare position.
- **Stop validation**: reject stops on the wrong side of price / absurdly far.
- **Heartbeat throttle**: idle log prints once/min instead of every 15s.
- **Gold data source swap**: Yahoo has no FX-spot gold; switched from gold
  *futures* (`GC=F`, was $60 off broker spot) to **`PAXG-USD`** (tokenized gold
  that tracks spot, ~$10 off).

---

## 3. Current status (what's working TODAY)

| Layer | Status |
|---|---|
| Swing scanner (GitHub) | ✅ live, every 5 min, London/NY hours |
| Scalp scanner (GitHub) | ✅ live, 1.5R + min-pip filter |
| Supabase + dashboard | ✅ live at `https://octanetraders.netlify.app` |
| Telegram alerts | ✅ instant via Edge Function |
| Copier (MT5 demo) | ✅ places orders (verified with test signals) |
| Admin page | ✅ accounts, risk %, kill-switch, close buttons |
| Data accuracy | ⚠️ FX = good; indices = futures-vs-CFD gap; gold fixed with PAXG |

### Verified end-to-end (proof it works)
A test signal → copier → MT5 → **real order placed** (ticket 14761858),
SL/TP attached, position recorded in admin, manual close detected & reconciled.

---

## 4. Known issues (the "new challenges" we were solving)

1. **Index data mismatch**: Yahoo gives index *futures* (`NQ=F`, `YM=F`, `ES=F`);
   broker gives *CFDs* (`NACUSD.c`, etc.). They track the same index but with a
   changing basis → NAS100 saw ~$90 gap → pending orders at futures-derived
   entries are meaningless on a CFD account.

2. **Latency**: signal → order takes ~2.5–5 min (GitHub 5-min cron + copier 15s
   poll). For scalp setups with small stops, the move is often already done.

3. **Pending orders on short-lived setups**: a 1R scalp whose TP/SL gets hit
   within 5 min doesn't make sense as a 30-min pending order.

---

## 5. The architecture decision we made (Option A + D)

After brainstorming, we chose:

- **A: Move the scalp engine INTO the copier** (co-located with MT5). It reads
  the **broker's own candles** (`copy_rates_from_pos`) every ~15s, so:
  - latency drops to ~15s (no GitHub cron),
  - index mismatch disappears (same CFD prices you trade),
  - Yahoo no longer matters for execution.

- **D: Keep swing on GitHub + Yahoo as PENDING orders** at the signal entry,
  because swing signals (20–40 pip targets, multi-hour life) have time to spare
  and pending-at-entry works well there.

### Critical design rule (for Stage 2)
Build the engine as a **standalone module** (`signal_engine.py`) with a clean
interface, and keep the copier as a thin executor. This is what makes Stage 2
possible without a rewrite.

---

## 6. Stage 2 — the subscriber plan (future)

**Goal:** multiple subscriber MT5 accounts taking the same trades simultaneously.

**Architecture (the "brain vs hands" split):**

```
BRAIN (one place, accurate data)         HANDS (many, parallel)
┌───────────────────────────────┐       ┌──────────────┬──────────────┐
│ Signal server (cloud VPS)     │       │ Account 1    │ Account 2 …  │
│ runs signal_engine every 10-30s│ ───▶ │ risk 0.5%    │ risk 1.0%    │
│ writes ONE signal to Supabase │       │ (lot sizing  │ (lot sizing  │
└───────────────────────────────┘       │  is per-acct)│  is per-acct)│
                                        └──────────────┴──────────────┘
```

- Signal written **once** → every account picks it up within seconds → skew
  between subscribers ~2–5s (fine for swing, acceptable for scalp).
- **Everything we already built carries over unchanged**: per-account risk %,
  lot calculator, positions table, admin close/kill-switch, performance report.

**The only NEW cost in Stage 2:**
- **MetaApi** (cloud MT5 bridge — you can't install a copier on each subscriber's
  PC). Roughly $20–40/mo platform + small per-account fee (~$0.15–0.30/account/day).
- A cloud VPS (~$10/mo) to run the signal server.
- Optionally: Supabase Auth + a server-side admin API (so credentials never touch
  the browser — Stage 1 stores them insert-only via anon, fine for demo only).

**Stage 2 checklist (future work):**
1. Move `signal_engine.py` to a VPS with an accurate data feed.
2. Add MetaApi execution layer (one account per subscriber).
3. Add Supabase Auth + admin Edge Function for secure account management.
4. Billing/entitlement per subscriber.
5. Legal/compliance (signal-selling rules in your jurisdiction).

---

## 7. Key files (in the repo)

| Path | What |
|---|---|
| `scanner.py` | Swing scanner (SMC + liquidity) |
| `research/scalp_engine.py` | Scalp scanner (5m momentum) |
| `copier/copier.py` | The trade copier (MT5 execution) |
| `copier/lot_calculator.py` | Risk-based lot sizing (round-down) |
| `copier/config.py` / `config_local.py` | Broker symbols + pip values |
| `copier/copier.ini` | Supabase creds + order mode |
| `.github/workflows/scan.yml` | Scheduled swing scan |
| `.github/workflows/scalp-scan.yml` | Scheduled scalp scan |
| `.github/workflows/build-copier.yml` | Builds the Windows .exe |
| `supabase/schema*.sql` | DB schema v1–v4 (signals, accounts, positions, commands) |
| `supabase/functions/telegram-alert/index.ts` | Instant Telegram Edge Function |
| `dashboard/` | Netlify site (index + admin pages) |

---

## 8. The next step (when we resume)

1. **Build `signal_engine.py`** — the broker-native scalp engine as a clean,
   reusable module (the "brain" of Option A).
2. **Test it on the MT5 demo** — read `copy_rates_from_pos`, generate signals
   on CFD prices, place market/pending orders within ~15s.
3. **Decide scalp entry mode** — market vs short-TTL limit (open question).
4. **Run forward on demo for 1–2 weeks**, compare against backtest.
5. **Then Stage 2** — VPS + MetaApi + subscriber accounts.

### Open decisions to resolve in the next chat
- Scalp entry: market order vs short-TTL limit at a better price?
- Keep Yahoo for swing, or also move swing to broker-native eventually?
- Gold: keep `PAXG-USD` proxy, or drop gold from auto-copy until we have a real spot feed?

---

## 9. Known quirks of my setup (so you don't rediscover them)

- **Broker**: Upcomers, server `Upcomers-Server`, account `1316503`, $25k demo.
- **CFD symbols**: `SPCUSD.c` (S&P), `NACUSD.c` (Nasdaq), `DJCUSD.c` (Dow).
- **FX symbols**: plain (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCAD`).
- **Gold**: `XAUUSD` (spot). **No FOK, no SL/TP on market orders, no pending
  expiration** — all handled by the copier's fallbacks.
- **Timezone**: America/Toronto (ET, DST-aware). Trading hours 03:00–17:00 ET,
  blackout 17:00–18:30 ET.
- **GitHub Actions** free tier: public repo = unlimited minutes; 5-min cron is
  the GitHub minimum.
- **Supabase project ref**: `yiklpoxuvtcjhvnhdphn`.
