#!/usr/bin/env python3
"""
Octane Traders — broker-native scalp engine (Option A).

Generates scalp signals from the broker's OWN candles via MT5's
`copy_rates_from_pos`. Because signals are computed on the exact CFD/FX prices
the account trades, there is no futures-vs-CFD mismatch and no Yahoo dependency
for execution — the old "index price variance" problem disappears entirely.

The strategy logic is identical to research/scalp_engine.py (5m momentum
pullback in the 15m trend), only the data source changed:

  * 15m bias     : EMA9 vs EMA21  (up / down / flat)
  * entry trigger: 5m RSI(14) pullback in the 15m direction
  * stop / target: 1 x ATR(14, 5m) / 1.5 x ATR(14, 5m)
  * min target   : 5 pips (FX) / 30 points (indices)

Pure signal generation — no Supabase, no orders. The copier decides what to do
with each returned dict (size + execute + record). This clean split is what
lets Stage 2 move the same module to a cloud signal server unchanged.
"""

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from config import SYMBOL_MAP

# ------------------------------------------------------------------ universe
SCALP_UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                  "SPX500", "NAS100", "US30"]

PIP_SIZE = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "USDCAD": 0.0001,
    "USDJPY": 0.01,
    "SPX500": 1.0, "NAS100": 1.0, "US30": 1.0,
}

IS_INDEX = {"SPX500", "NAS100", "US30"}

# strategy parameters (mirror research/scalp_engine.py)
RSI_N = 14
ATR_N = 14
RSI_BUY = 38.0
RSI_SELL = 62.0
SL_ATR = 1.0
TP_ATR = 1.5
MIN_PIPS_FX = 5.0
MIN_PTS_IDX = 30.0
LOOKBACK_15M = 120
LOOKBACK_5M = 120


# ------------------------------------------------------------------ pure math
def ema(vals, n):
    if not vals:
        return []
    k = 2.0 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=RSI_N):
    if len(closes) < n + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(rows, n=ATR_N):
    trs = []
    for i in range(1, len(rows)):
        _, o, h, l, c = rows[i]
        pc = rows[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-n:]) / n if len(trs) >= n else 0.0


def bias_15m(rows15):
    closes = [r[4] for r in rows15]
    if len(closes) < 60:
        return "flat", 0.0
    e9, e21 = ema(closes, 9), ema(closes, 21)
    if e9[-1] > e21[-1] and closes[-1] > e21[-1]:
        return "up", (e9[-1] - e21[-1]) / e21[-1]
    if e9[-1] < e21[-1] and closes[-1] < e21[-1]:
        return "down", (e21[-1] - e9[-1]) / e21[-1]
    return "flat", 0.0


# ------------------------------------------------------------------ signal
def signal_from_rates(asset, rows15, rows5):
    """Pure, testable core (no MT5). rows are (time, open, high, low, close).
    Returns a signal dict or None."""
    if len(rows15) < 60 or len(rows5) < ATR_N + 2:
        return None
    bdir, _ = bias_15m(rows15)
    if bdir == "flat":
        return None
    closes5 = [r[4] for r in rows5]
    r = rsi(closes5)
    a = atr(rows5)
    if a <= 0:
        return None
    price = rows5[-1][4]
    pip = PIP_SIZE.get(asset, 0.0001)
    if bdir == "up" and r < RSI_BUY:
        side = "LONG"
        sl = price - SL_ATR * a
        tp = price + TP_ATR * a
    elif bdir == "down" and r > RSI_SELL:
        side = "SHORT"
        sl = price + SL_ATR * a
        tp = price - TP_ATR * a
    else:
        return None
    if sl <= 0 or tp <= 0:
        return None
    pips_sl = abs(price - sl) / pip
    pips_tp = abs(price - tp) / pip
    min_t = MIN_PTS_IDX if asset in IS_INDEX else MIN_PIPS_FX
    if pips_tp < min_t:
        return None
    return {
        "asset": asset,
        "side": side,
        "price": round(float(price), 5),
        "sl": round(float(sl), 5),
        "tp": round(float(tp), 5),
        "pips_sl": round(pips_sl, 1),
        "pips_tp": round(pips_tp, 1),
        "rr": round(TP_ATR / SL_ATR, 2),
        "bias": bdir,
        "rsi": round(r, 1),
        "strategy": "scalp",
    }


# ------------------------------------------------------------------ MT5 glue
def _rows(rates):
    if rates is None:
        return []
    out = []
    for i in range(len(rates)):
        out.append((int(rates[i]["time"]), float(rates[i]["open"]),
                    float(rates[i]["high"]), float(rates[i]["low"]),
                    float(rates[i]["close"])))
    return out


def compute_signals(symbol_map=None):
    """Pull 15m + 5m candles from the CURRENT MT5 connection for every symbol
    in the scalp universe and return a list of broker-native signal dicts."""
    if not MT5_AVAILABLE:
        return []
    mapping = symbol_map or SYMBOL_MAP
    sigs = []
    for asset in SCALP_UNIVERSE:
        sym = mapping.get(asset)
        if not sym:
            continue
        if not mt5.symbol_select(sym, True):
            continue
        r15 = _rows(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, LOOKBACK_15M))
        r5 = _rows(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, LOOKBACK_5M))
        s = signal_from_rates(asset, r15, r5)
        if s:
            s["symbol"] = sym
            sigs.append(s)
    return sigs
