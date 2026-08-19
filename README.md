# ⚡ Octane Traders

**An automated Smart Money Concepts (SMC) + Liquidity signal system for forex & gold.**

Octane Traders scans the market every 5 minutes, finds high-quality SMC setups
(liquidity sweeps + order blocks + fair value gaps), filters them down to a
focused, backtested subset, and pushes live alerts to Telegram — with a live
dashboard that tracks every trade and the system's real performance.

> 📦 **New here? Start with [INSTALL.md](INSTALL.md)** — it walks through the
> full setup step by step.
>
> 📊 **Validation?** See [docs/backtest-report.html](docs/backtest-report.html)
> — the full research report with every backtest we ran.

---

## What it does

```
┌──────────────────────┐   POST (service-role key)   ┌──────────────┐   SELECT + Realtime (anon key)   ┌───────────────┐
│  GitHub repo +       │ ───────────────────────────▶ │   Supabase   │ ───────────────────────────────▶ │  Netlify site │
│  Actions (scanner.py)│                              │  (Postgres)  │                                   │  (dashboard/) │
│  runs every 5 min    │                              └──────────────┘                                   └───────────────┘
└──────────┬───────────┘                                                                                          │
           └──────────────────────────▶ Telegram alerts (new signals + TP/SL) ◀──────────────────────────────────┘
```

**The whole thing runs for free** on GitHub Actions + Supabase + Netlify — no
server, no always-on computer, no cost.

## The strategy (what it trades)

- **Universe:** EURUSD, AUDUSD, XAUUSD (gold), USDJPY — clean, liquid pairs.
- **Setup:** a liquidity sweep (stop-hunt wick + reclaim) into an Order Block /
  Fair Value Gap, targeting the next untapped liquidity pool.
- **Filters (all backtest-proven):**
  - Quality score **70–89** (the 90+ "chase zone" loses money)
  - **Bias-aligned** — trade only WITH the 1H trend
  - **Session-filtered** — London/NY hours only (03:00–17:00 ET)
  - **Blackout** — silent during the 17:00–18:30 ET rollover spread spike
- **Risk:** TP at the next liquidity pool (≥20 pips), SL beyond structure,
  R:R ≥ 1.5.

## Measured performance

From the walk-forward backtest (see the report for methodology and caveats):

| Metric | Value |
|---|---|
| Signals | ~2.5 high-quality/day |
| Win rate | 40.3% |
| Avg R:R on winners | ~3.0 |
| Expectancy | **+0.62R/trade** |
| Walk-forward P&L | +92.5R over the test window |

> ⚠️ Historical backtest = one market regime. The system is designed for
> **forward-testing on demo first** before any real capital. See the report's
> caveats section.

## Two strategies, one dashboard

The dashboard has two tabs:

| Tab | Strategy | Target | Win rate (backtest) | Expectancy |
|---|---|---|---|---|
| **Swing** | SMC + liquidity (15m) | 2–4R at liquidity pools | 40.3% | +0.62R/trade |
| **Aggressive Scalp** | 5m momentum pullbacks (1m/5m timing) | **1R** (or 1.5R) | **60.9%** | +0.22R/trade |

The scalp engine trades high-liquidity FX + indices (EURUSD, GBPUSD, USDJPY,
AUDUSD, USDCAD, SPX500, NAS100, US30) with 1×ATR stops and targets, London/NY
hours only. More wins, smaller targets — for traders who want frequent action.

## Features

- ⚡ 5-minute scanning on GitHub Actions (free, no computer needed)
- 🚨 Instant Telegram alerts on new signals + automatic TP/SL hit messages
- 📊 Live dashboard with **two tabs**, equity curve, win-rate tracker, per-pair breakdowns
- 📤 One-click "re-send to Telegram" from the dashboard
- 📈 Auto outcome tracking (TP/SL marked automatically from live price)
- 🕐 Session + blackout filters to keep fake signals out of your data
- 📦 Everything in one page — signal history, backtest history, equity chart

## Folder layout

| Path | What |
|---|---|
| `scanner.py` | Swing engine — SMC detection (stdlib-only Python) |
| `research/scalp_engine.py` | Scalp engine — 5m momentum pullbacks (1R/1.5R targets) |
| `.github/workflows/` | Scheduled scan + scalp scan + test + demo-signal buttons |
| `supabase/` | Database schema + security rules |
| `dashboard/` | The web dashboard (static site for Netlify) |
| `docs/backtest-report.html` | Full research & validation report (swing) |
| `research/pairs_engine.py` | Experimental pairs-trading engine (rejected — kept for reference) |
