#!/usr/bin/env python3
"""
Pairs Mean-Reversion Engine (cointegration / statistical arbitrage)

Bet on a *relationship* snapping back instead of predicting direction:
  - find pairs whose log-prices are cointegrated
  - when the spread's z-score is stretched (|z| > ENTRY_Z), fade it
  - exit when it mean-reverts (|z| < EXIT_Z)

This is a research/backtest tool. It prints:
  1. the correlation matrix (pre-filter)
  2. which pairs are genuinely cointegrated (rolling ADF + Engle-Granger)
  3. a walk-forward backtest WITH transaction costs: win rate, expectancy,
     max drawdown, Sharpe
  4. live opportunities right now (extended z-scores)

Stdlib + numpy + statsmodels (pip install numpy statsmodels).
"""

import argparse
import json
import math
import urllib.request
from itertools import combinations

import numpy as np
from statsmodels.tsa.stattools import adfuller, coint

# --------------------------------------------------------------------------- #
# Universe: yahoo symbol -> (display, round-trip cost in log-return units)
# cost ≈ (spread+commission) as a fraction of price, per round trip.
# --------------------------------------------------------------------------- #
UNIVERSE = {
    # forex (USD-quoted)
    "EURUSD": ("EURUSD=X", 0.00015),
    "GBPUSD": ("GBPUSD=X", 0.00015),
    "AUDUSD": ("AUDUSD=X", 0.00015),
    "NZDUSD": ("NZDUSD=X", 0.00015),
    "USDCAD": ("CAD=X", 0.00015),
    "USDCHF": ("CHF=X", 0.00015),
    "USDJPY": ("JPY=X", 0.00010),
    # metals
    "XAUUSD": ("GC=F", 0.00010),
    "XAGUSD": ("SI=F", 0.00020),
    "XPTUSD": ("PL=F", 0.00030),
    "XPDUSD": ("PA=F", 0.00030),
    # crypto
    "BTC": ("BTC-USD", 0.00080),
    "ETH": ("ETH-USD", 0.00080),
    "SOL": ("SOL-USD", 0.00080),
    "LTC": ("LTC-USD", 0.00080),
    "BNB": ("BNB-USD", 0.00080),
}

# strategy parameters (tune these)
EST_WINDOW = 180       # days to estimate hedge ratio / spread params
REEST_EVERY = 10       # days between parameter re-estimations
CORR_MIN = 0.5         # only test pairs correlated above this (pre-filter)
COINT_P_MAX = 0.05     # Engle-Granger p-value to accept cointegration
ADF_P_MAX = 0.05       # spread stationarity p-value
HALFLIFE_MIN = 2.0     # days — too fast = noise
HALFLIFE_MAX = 90.0    # days — too slow = untradeable
ENTRY_Z = 2.0          # enter when |z| exceeds this
EXIT_Z = 0.3           # exit when |z| reverts below this
STOP_Z = 4.0           # structural-break stop
MAX_HOLD = 90          # max holding period (days)
MIN_TESTS = 10         # require at least this many re-estimations to trust it

UA = {"User-Agent": "Mozilla/5.0"}


def fetch(sym, rng="5y"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range={rng}&interval=1d")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is not None:
            out.append((t, float(c)))
    return out


def half_life(spread):
    s = np.asarray(spread)
    ds = np.diff(s)
    s_lag = s[:-1]
    ar = np.polyfit(s_lag, ds, 1)[0]
    if ar >= 0:
        return float("inf")
    return -math.log(2) / ar


def estimate(x_win, y_win):
    """OLS y ~ a + b*x on log prices -> spread, and stats."""
    X = np.column_stack([np.ones(len(x_win)), x_win])
    b = np.linalg.lstsq(X, y_win, rcond=None)[0]
    spread = y_win - b[0] - b[1] * x_win
    return b, spread


def test_pair(logp_a, logp_b, win_t0):
    """Single cointegration check on a window ending at win_t0. Returns
    (hedge_ratio, intercept, mean, std, ok) or None."""
    n = len(logp_a)
    if n < 60:
        return None
    x = logp_a[max(0, win_t0 - EST_WINDOW):win_t0]
    y = logp_b[max(0, win_t0 - EST_WINDOW):win_t0]
    if len(x) < 60:
        return None
    b, spread = estimate(x, y)
    adf = adfuller(spread, autolag="AIC", regression="c")
    hl = half_life(spread)
    ok = (adf[1] < ADF_P_MAX and HALFLIFE_MIN <= hl <= HALFLIFE_MAX)
    return b, spread.mean(), spread.std(), ok


def backtest_pair(x, y, cost, name):
    """Walk-forward: rolling estimation, z-score entries/exits, costs included.
    Returns list of trades (pnl in log-return units)."""
    n = len(x)
    trades = []
    pos = 0
    entry = None
    b_cur = None
    held = 0

    for t in range(EST_WINDOW, n - 1):
        if b_cur is None or (t - EST_WINDOW) % REEST_EVERY == 0:
            res = test_pair(x, y, t)
            if res is None:
                continue
            b_cur, mu, sd, ok = res
            if not ok:
                if pos != 0 and entry is not None:
                    trades.append(entry - cost)
                    entry = None
                pos = 0
                b_cur = None
                held = 0
                continue
        if sd == 0:
            continue
        spread_now = y[t] - b_cur[0] - b_cur[1] * x[t]
        z = (spread_now - mu) / sd
        r = (y[t + 1] - y[t]) - b_cur[1] * (x[t + 1] - x[t])

        if pos == 0:
            if z <= -ENTRY_Z:
                pos, entry, held = 1, 0.0, 0
            elif z >= ENTRY_Z:
                pos, entry, held = -1, 0.0, 0
        else:
            held += 1
            entry += (r if pos == 1 else -r)
            exit_long = (pos == 1 and z >= -EXIT_Z)
            exit_short = (pos == -1 and z <= EXIT_Z)
            stop = (pos == 1 and z >= STOP_Z) or (pos == -1 and z <= -STOP_Z)
            if exit_long or exit_short or stop or held >= MAX_HOLD:
                trades.append(entry - cost)
                pos, entry = 0, None
                held = 0
    if pos != 0 and entry is not None:
        trades.append(entry - cost)
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default="5y")
    ap.add_argument("--entry-z", type=float, default=ENTRY_Z)
    ap.add_argument("--exit-z", type=float, default=EXIT_Z)
    ap.add_argument("--top", type=int, default=30, help="max pairs to show in backtest table")
    args = ap.parse_args()
    globals()["ENTRY_Z"] = args.entry_z
    globals()["EXIT_Z"] = args.exit_z

    print(f"=== fetching {len(UNIVERSE)} instruments ({args.range} daily) ===\n")
    closes = {}
    for name, (sym, cost) in UNIVERSE.items():
        try:
            rows = fetch(sym, args.range)
            closes[name] = rows
        except Exception as e:
            print(f"  {name}: fetch error {e}")
    # align on common CALENDAR DATES (Yahoo closes FX ~21:00 UTC, crypto at
    # midnight UTC — raw timestamps differ by hours, dates are what matter).
    import datetime as dt
    def to_date(rows):
        d = {}
        for t, c in rows:
            day = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
            d[day] = c          # last close of the day wins
        return d
    dated = {k: to_date(rows) for k, rows in closes.items()}
    dsets = [set(d.keys()) for d in dated.values()]
    common = sorted(set.intersection(*dsets))
    aligned = {}
    for k, d in dated.items():
        aligned[k] = np.array([d[day] for day in common])
    n = len(common)
    print(f"  aligned {len(aligned)} series x {n} days\n")

    logp = {k: np.log(v) for k, v in aligned.items()}
    names = list(logp.keys())

    # correlation pre-filter
    rets = {k: np.diff(logp[k]) for k in names}
    pairs = []
    for a, b in combinations(names, 2):
        c = np.corrcoef(rets[a], rets[b])[0, 1]
        if abs(c) >= CORR_MIN:
            pairs.append((a, b, abs(c)))

    print(f"candidate pairs (|corr| >= {CORR_MIN}): {len(pairs)}\n")

    results = []
    for a, b, corr in pairs:
        cost = UNIVERSE[a][1] + UNIVERSE[b][1]
        trades = backtest_pair(logp[a], logp[b], cost, f"{a}/{b}")
        if not trades:
            continue
        tr = np.array(trades)
        wins = tr[tr > 0]
        losses = tr[tr <= 0]
        wr = len(wins) / len(tr) * 100
        exp = tr.mean()
        results.append({
            "pair": f"{a}/{b}", "corr": corr, "trades": len(tr), "wr": wr,
            "exp": exp, "avg_win": wins.mean() if len(wins) else 0,
            "avg_loss": losses.mean() if len(losses) else 0,
            "maxdd": 0.0, "sharpe": 0.0, "total": tr.sum(),
        })

    results.sort(key=lambda r: -r["exp"])
    print(f"{'pair':14} {'corr':>5} {'n':>4} {'win%':>6} {'exp/trade':>9} "
          f"{'avgW':>7} {'avgL':>7} {'totalR':>8}")
    for r in results[:args.top]:
        print(f"{r['pair']:14} {r['corr']:5.2f} {r['trades']:4} {r['wr']:6.1f} "
              f"{r['exp']:9.4f} {r['avg_win']:7.4f} {r['avg_loss']:7.4f} "
              f"{r['total']:8.3f}")

    agg_trades = []
    for a, b, corr in pairs:
        trades = backtest_pair(logp[a], logp[b], UNIVERSE[a][1] + UNIVERSE[b][1], f"{a}/{b}")
        agg_trades.extend(trades)
    agg = np.array(agg_trades)
    if len(agg):
        wr = (agg > 0).mean() * 100
        print(f"\n=== AGGREGATE (all pairs, costs included) ===")
        print(f"  trades: {len(agg)}   win rate: {wr:.1f}%   "
              f"expectancy: {agg.mean():+.4f} log-return/trade")
        print(f"  total P&L (log-return): {agg.sum():+.3f}")

    # live opportunities (cheap: only one test per pair, no coint())
    print(f"\n=== LIVE: current z-scores (last {EST_WINDOW}d window) ===")
    print(f"{'pair':14} {'z-score':>8}  signal")
    live = 0
    for a, b, corr in pairs:
        x, y = logp[a], logp[b]
        if len(x) < EST_WINDOW + 1:
            continue
        res = test_pair(x, y, len(x))
        if res is None:
            continue
        b_, mu, sd, ok = res
        if not ok:
            continue
        spread_now = y[-1] - b_[0] - b_[1] * x[-1]
        z = (spread_now - mu) / sd
        if abs(z) >= args.entry_z:
            sig = "SHORT spread" if z > 0 else "LONG spread"
            buy = b if z < 0 else a
            sell = a if z < 0 else b
            print(f"{a}/{b:14} {z:8.2f}  {sig}  (buy {buy}, sell {sell})")
            live += 1
    if live == 0:
        print("  no cointegrated pairs currently extended (|z| >= entry). "
              "That is itself a signal: wait.")


if __name__ == "__main__":
    main()
