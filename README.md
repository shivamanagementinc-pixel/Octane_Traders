# SMC + Liquidity Confluence Scanner

> **Full deployment guide (Supabase + GitHub Actions + Netlify):**
> see [DEPLOY.md](DEPLOY.md). This README documents the scanner itself.

A stdlib-only Python scanner that finds **SMC (Smart Money Concepts) + liquidity**
setups on forex/gold and only flags trades that pass two filters:

1. **≥ 20 pips of potential** to the next untapped liquidity pool (default, configurable)
2. **Quality score ≥ 70/100** (weighted confluence, default)

## Run it

```bash
python3 scanner.py                          # scan default pairs once
python3 scanner.py --pairs EURUSD USDJPY XAUUSD
python3 scanner.py --min-pips 20 --min-score 80
python3 scanner.py --repeat 20 --interval 60   # watch mode: rescan every 60s × 20
python3 scanner.py --verbose                    # also show below-threshold near-misses
```

Data comes from Yahoo Finance's chart API (15m bars for structure, 1h for bias).
No API key needed. Prices are near-live (usually a few seconds of delay).

## What it detects (and how the score works)

The quality score is the sum of weighted SMC confluences (max 100):

| Confluence | Weight |
|---|---|
| HTF (1H) bias agrees with trade | +20 (flat +8, **against −25**) |
| Liquidity swept & reclaimed | +25 |
| Inside Order Block (OB) | +20 |
| Inside Fair Value Gap (FVG) | +15 |
| Premium/Discount correct for side | +10 (mid +3, wrong side −5) |
| Risk:reward ≥ 2 | +10 (≥1.5 = +5) |

**SMC logic implemented**

- **Market structure** — swing highs/lows (2-bar), equal highs/equal lows
  (liquidity pools).
- **Liquidity sweep** — a wick below a recent swing low that closes back above
  = *sell-side* liquidity taken (bullish). A wick above a swing high that
  closes back below = *buy-side* liquidity taken (bearish).
- **Order blocks** — the last opposing candle before displacement.
- **Fair value gaps** — 3-candle imbalance zones.
- **Premium/Discount** — price position inside the dealing range (last 3 swing
  highs/lows). In an uptrend you want to buy in discount/equilibrium.
- **Liquidity flow** — the target is always the next untapped pool in the trade
  direction (the "magnet" price is drawn toward).

## Signal anatomy (what each line means)

```
★ GBPJPY LONG  —  QUALITY 93/100
   price 216.005   zone [215.999 – 216.004] (FVG)
   SL 215.950  (5.5 pips)   TP 216.216  (21.1 pips)   R:R 3.87
   liquidity: liq swept @ 215.96899 + reclaimed | flow up | HTF bull | deal pos 48.6%
   why: HTF(1H) bullish · sell-side liq swept below lows + reclaim · ...
```

- **Entry** = current price (it only flags when price is *already inside* the
  OB/FVG zone, so you can act now or set a limit into the zone).
- **SL** = beyond the swept level / zone edge + an ATR-scaled buffer
  (never tighter than `--min-sl-pips`, default 5).
- **TP** = next liquidity pool (swing high/low or equal highs/lows) in the trade
  direction — only if ≥ `--min-pips` away.
- **★** = score ≥ 80 (high quality), **●** = ≥ threshold, **·** = below.

## Tunable knobs (CLI flags)

| Flag | Default | What it does |
|---|---|---|
| `--min-pips` | 20 | minimum TP distance (pips; $ for gold) |
| `--min-score` | 70 | minimum quality to print |
| `--max-score` | 89 | score ceiling — 90+ is the "chase zone" (backtest: it loses) |
| `--telegram-cooldown-hours` | 1 | min hours between Telegram pings per pair+side |
| `--rr-min` | 1.5 | minimum risk:reward |
| `--min-sl-pips` | 5 | reject stops tighter than this |
| `--eq-pips` | 3 | tolerance for "equal" highs/lows |
| `--sl-buffer` | 1 | extra pips beyond structure for the stop |
| `--sweep-lookback` | 8 | bars to look back for a recent sweep |
| `--swing-n` | 2 | swing detection lookback |
| `--blackout-start` | 17:00 | daily no-trade window start (HH:MM) |
| `--blackout-end` | 18:30 | daily no-trade window end (HH:MM) |
| `--blackout-tz` | America/Toronto | timezone for the window (DST-aware) |
| `--no-blackout` | off | disable the blackout window |
| `--session-start` | 03:00 | active-hours start (London open, ET) |
| `--session-end` | 17:00 | active-hours end (NY close, ET) |
| `--session-tz` | America/Toronto | timezone for active hours |
| `--no-session-filter` | off | scan 24/5 instead of session-only |
| `--no-bias-filter` | off | allow counter-trend signals |
| `--telegram-test` | off | send a Telegram test message and exit |

## Known limitations (be honest about these)

- **Premium/discount uses the last 3 swings.** In a tight consolidation the
  "deal pos" can read 100%/0% — treat it as a minor factor, not gospel.
- **OB/FVG detection is simplified** (displacement-based). No multi-timeframe
  OB confirmation or "mitigation" tracking yet.
- **Yahoo data has a few seconds' delay** and occasional gaps — fine for 15m
  swing scalps, not for sub-second latency games.
- **No session filter.** The Asia/EU/NY session makes a big difference to
  follow-through; add your own session window.
- **20 pips on gold = $20.** The `--min-pips` flag is in pips for FX and
  dollars for XAUUSD.

## Backtested edge (60 days, train/test split)

The default config was chosen and refined from backtests. Every filter below
was verified out-of-sample (train 30d / test 30d):

| Config | Signals/day | Win rate | Expectancy (test) |
|---|---|---|---|
| Old: 9 pairs, ≥70 | ~92 (spam) | 24.6% | −0.03R (losing) |
| 4 pairs, 70–89 | ~9 | 29% | +0.16R |
| **+ bias alignment** | ~4 | 36% | +0.21R |
| **+ London/NY session** | **~2.5** | **40%** | **+0.33R (test) / +0.62R (all)** |
| 90+ "chase zone" | — | 22% | −0.12R (dropped) |

**Final default:** 4 pairs (EURUSD, AUDUSD, XAUUSD, USDJPY) · score 70–89 ·
bias-aligned (trade WITH the 1H trend) · London/NY hours (03:00–17:00 ET) ·
blackout 17:00–18:30 ET.

That's ~2.5 high-quality signals/day at 40% win rate and +0.6R expectancy —
fewer trades, each one better. Counter-trend signals are dropped, off-hours
chop is skipped.

Caveats: 60 days = one regime, no spread/slippage modeled (costs are minor on
majors/gold, ~0.1R), Yahoo 15m data may have occasional gaps. Treat the signal
as a *candidate*, confirm the entry on M1/M5 inside the zone.

## Next upgrades (if you want them)

1. Session filter (London/NY/Asia) + kill-switch around red news.
2. HTF bias from 4H structure (BOS/CHoCH), not just 1H EMAs.
3. CHoCH/reversal detection for counter-trend setups.
4. A "watch list" mode that logs every signal to CSV for backtesting win-rate.
5. Webhook/Discord alert when a ★ setup appears.
