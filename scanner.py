#!/usr/bin/env python3
"""
SMC + Liquidity confluence scanner  (forex / gold)

Finds tradeable setups that pass BOTH filters:
  1. pip potential to the next liquidity pool >= MIN_PIPS  (default 20)
  2. SMC confluence quality score >= MIN_SCORE            (default 70)

SMC concepts implemented
------------------------
  * Market structure : swing highs/lows (n-bar), equal highs/lows = liquidity pools
  * Liquidity        : buy-side / sell-side sweeps (stop-hunt wick + reclaim)
  * Order Blocks (OB): last opposing candle before displacement
  * Fair Value Gaps  : 3-candle imbalance zones
  * Premium/Discount : price position inside the dealing range (last swing range)
  * HTF bias         : 1H EMA9/EMA21/EMA55 structure

Usage
-----
  python3 scanner.py
  python3 scanner.py --pairs EURUSD GBPUSD USDJPY XAUUSD
  python3 scanner.py --min-pips 20 --min-score 70
  python3 scanner.py --repeat 20 --interval 60   # rescan every 60s, 20 times

Stdlib only — no dependencies.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Instrument config: yahoo symbol -> pip/point size
# --------------------------------------------------------------------------- #
INSTRUMENTS = {
    "EURUSD": ("EURUSD=X", 0.0001),
    "GBPUSD": ("GBPUSD=X", 0.0001),
    "AUDUSD": ("AUDUSD=X", 0.0001),
    "NZDUSD": ("NZDUSD=X", 0.0001),
    "USDCAD": ("CAD=X", 0.0001),
    "USDCHF": ("CHF=X", 0.0001),
    "USDJPY": ("JPY=X", 0.01),
    "GBPJPY": ("GBPJPY=X", 0.01),
    "EURJPY": ("EURJPY=X", 0.01),
    "AUDJPY": ("AUDJPY=X", 0.01),
    "CHFJPY": ("CHFJPY=X", 0.01),
    "CADJPY": ("CADJPY=X", 0.01),
    "XAUUSD": ("GC=F", 1.0),   # gold: 1 "point" = $1
}

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                 "GBPJPY", "EURJPY", "AUDJPY", "XAUUSD"]

UA = {"User-Agent": "Mozilla/5.0"}


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def fetch(sym, interval, rng):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range={rng}&interval={interval}&includePrePost=false")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        rows.append((t, float(o), float(h), float(l), float(c)))
    return rows


# --------------------------------------------------------------------------- #
# Technical primitives
# --------------------------------------------------------------------------- #
def ema(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def atr(rows, n=14):
    trs = []
    for i in range(1, len(rows)):
        _, o, h, l, c = rows[i]
        pc = rows[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return 0.0
    return sum(trs[-n:]) / n


def swings(rows, n=2):
    """Return [(index, 'H'/'L', level)] swing points."""
    out = []
    for i in range(n, len(rows) - n):
        h, l = rows[i][2], rows[i][3]
        is_h = (all(h >= rows[i - j][2] for j in range(1, n + 1))
                and all(h >= rows[i + j][2] for j in range(1, n + 1))
                and (h > rows[i - 1][2] or h > rows[i + 1][2]))
        is_l = (all(l <= rows[i - j][3] for j in range(1, n + 1))
                and all(l <= rows[i + j][3] for j in range(1, n + 1))
                and (l < rows[i - 1][3] or l < rows[i + 1][3]))
        if is_h:
            out.append((i, "H", h))
        if is_l:
            out.append((i, "L", l))
    out.sort(key=lambda x: x[0])
    return out


def pools(swings, kind, tol):
    """Equal highs (kind='H') / equal lows (kind='L') -> [(level, count)]."""
    lvls = [(i, lvl) for i, k, lvl in swings if k == kind]
    groups = []
    for i, lvl in lvls:
        placed = False
        for g in groups:
            if abs(g[0] - lvl) <= tol:
                g[1] += 1
                placed = True
                break
        if not placed:
            groups.append([lvl, 1])
    return [(g[0], g[1]) for g in groups if g[1] >= 2]


def sweep(rows, swings, kind, lookback):
    """Detect a recent liquidity sweep.

    kind='L': wick below a swing low then close back above  -> buy-side sweep (bullish)
    kind='H': wick above a swing high then close back below -> sell-side sweep (bearish)
    """
    levels = [(i, lvl) for i, k, lvl in swings if k == kind and i < len(rows) - lookback]
    if not levels:
        return None
    for i, lvl in reversed(levels[-3:]):
        for j in range(max(len(rows) - lookback, i + 1), len(rows)):
            if kind == "H" and rows[j][2] > lvl and rows[j][4] < lvl:
                return lvl
            if kind == "L" and rows[j][3] < lvl and rows[j][4] > lvl:
                return lvl
    return None


def order_blocks(rows):
    """[(kind, lo, hi)] — bull OB = bearish candle then displacement up, etc."""
    obs = []
    for i in range(1, len(rows) - 1):
        _, o, h, l, c = rows[i]
        if c < o and i + 1 < len(rows) and rows[i + 1][4] > h:
            obs.append(("bull", l, h))
        if c > o and i + 1 < len(rows) and rows[i + 1][4] < l:
            obs.append(("bear", l, h))
    return obs


def fvgs(rows):
    """[(kind, lo, hi)] — 3-candle imbalance zones."""
    f = []
    for i in range(1, len(rows) - 1):
        h0, l0 = rows[i - 1][2], rows[i - 1][3]
        h2, l2 = rows[i + 1][2], rows[i + 1][3]
        if l0 > h2:
            f.append(("bull", h2, l0))
        if h0 < l2:
            f.append(("bear", h0, l2))
    return f


def htf_bias(rows):
    closes = [r[4] for r in rows]
    if len(closes) < 60:
        return "flat"
    e9, e21, e55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
    if e21[-1] > e55[-1] and closes[-1] > e21[-1]:
        return "bull"
    if e21[-1] < e55[-1] and closes[-1] < e21[-1]:
        return "bear"
    return "flat"


# --------------------------------------------------------------------------- #
# Setup evaluation
# --------------------------------------------------------------------------- #
def evaluate(pair, rows15, rows1h, cfg):
    """Return a signal dict, or None."""
    pip = cfg["pip"]
    price = rows15[-1][4]
    sw = swings(rows15, cfg["swing_n"])
    sh = [s for s in sw if s[1] == "H"]
    sl = [s for s in sw if s[1] == "L"]
    if len(sh) < 3 or len(sl) < 3:
        return None

    a = atr(rows15) or 0.001
    tol = 0.6 * a                      # zone tolerance
    eq_tol = cfg["eq_pips"] * pip

    obs = order_blocks(rows15)
    fvs = fvgs(rows15)
    bias = htf_bias(rows1h)

    # dealing range from last 3 swings each side
    hi = max(s[2] for s in sh[-3:])
    lo = min(s[2] for s in sl[-3:])
    mid = (hi + lo) / 2
    pos = (price - lo) / (hi - lo) * 100 if hi > lo else 50.0

    sweep_low = sweep(rows15, sw, "L", cfg["sweep_lookback"])   # sell-side liq swept = bullish
    sweep_high = sweep(rows15, sw, "H", cfg["sweep_lookback"])  # buy-side liq swept = bearish

    for side in ("LONG", "SHORT"):
        zones = []
        if side == "LONG":
            zones = [(lo_, hi_, "OB") for k, lo_, hi_ in obs if k == "bull"] + \
                    [(lo_, hi_, "FVG") for k, lo_, hi_ in fvs if k == "bull"]
            sweep_lvl = sweep_low
        else:
            zones = [(lo_, hi_, "OB") for k, lo_, hi_ in obs if k == "bear"] + \
                    [(lo_, hi_, "FVG") for k, lo_, hi_ in fvs if k == "bear"]
            sweep_lvl = sweep_high

        # active zones near price
        active = [z for z in zones if z[0] - tol <= price <= z[1] + tol]
        if not active:
            continue
        zone = min(active, key=lambda z: abs(price - (z[0] + z[1]) / 2))
        z_lo, z_hi, z_type = zone
        in_ob = any(z[2] == "OB" for z in active)
        in_fvg = any(z[2] == "FVG" for z in active)

        # liquidity target: nearest pool beyond entry (>= min pips)
        min_dist = cfg["min_pips"] * pip
        if side == "LONG":
            pools_hi = pools(sw, "H", eq_tol)
            cands = [lvl for lvl, _ in pools_hi if lvl > price + min_dist] + \
                    [s[2] for s in sh if s[2] > price + min_dist]
            tp = min(cands) if cands else None
            buf = max(cfg["sl_buffer"] * pip, 0.3 * a)
            sup = [z_lo] + ([sweep_lvl] if sweep_lvl else [])
            sl_px = min(sup) - buf
        else:
            pools_lo = pools(sw, "L", eq_tol)
            cands = [lvl for lvl, _ in pools_lo if lvl < price - min_dist] + \
                    [s[2] for s in sl if s[2] < price - min_dist]
            tp = max(cands) if cands else None
            buf = max(cfg["sl_buffer"] * pip, 0.3 * a)
            res = [z_hi] + ([sweep_lvl] if sweep_lvl else [])
            sl_px = max(res) + buf

        if tp is None:
            continue
        if side == "LONG" and sl_px >= price:
            continue
        if side == "SHORT" and sl_px <= price:
            continue

        pip_tp = (tp - price) / pip if side == "LONG" else (price - tp) / pip
        pip_sl = (price - sl_px) / pip if side == "LONG" else (sl_px - price) / pip
        if pip_sl <= 0:
            continue
        if pip_sl < cfg["min_sl_pips"]:
            continue   # stop too tight -> fragile setup, skip
        rr = pip_tp / pip_sl
        if rr < cfg["rr_min"]:
            continue
        if pip_tp < cfg["min_pips"]:
            continue

        # ------------------ scoring ------------------ #
        score = 0
        reasons = []

        if side == "LONG":
            if bias == "bull":
                score += 20; reasons.append("HTF(1H) bullish")
            elif bias == "flat":
                score += 8; reasons.append("HTF(1H) flat")
            else:
                score -= 25; reasons.append("HTF(1H) BEARISH (against)")
            if sweep_lvl is not None:
                score += 25; reasons.append(f"sell-side liq swept below lows ({sweep_lvl:.5f}) + reclaim")
            if pos < 45:
                score += 10; reasons.append(f"discount ({pos:.0f}%)")
            elif pos > 55:
                score -= 5; reasons.append(f"premium ({pos:.0f}%)")
            else:
                score += 3; reasons.append("mid-range (equilibrium)")
        else:
            if bias == "bear":
                score += 20; reasons.append("HTF(1H) bearish")
            elif bias == "flat":
                score += 8; reasons.append("HTF(1H) flat")
            else:
                score -= 25; reasons.append("HTF(1H) BULLISH (against)")
            if sweep_lvl is not None:
                score += 25; reasons.append(f"buy-side liq swept above highs ({sweep_lvl:.5f}) + reclaim")
            if pos > 55:
                score += 10; reasons.append(f"premium ({pos:.0f}%)")
            elif pos < 45:
                score -= 5; reasons.append(f"discount ({pos:.0f}%)")
            else:
                score += 3; reasons.append("mid-range (equilibrium)")

        if in_ob:
            score += 20; reasons.append("inside Order Block")
        if in_fvg:
            score += 15; reasons.append("inside FVG")

        if rr >= 2.0:
            score += 10; reasons.append(f"R:R {rr:.2f} (>=2)")
        elif rr >= cfg["rr_min"]:
            score += 5; reasons.append(f"R:R {rr:.2f} (>=1.5)")

        score = max(0, min(100, score))

        flow = ("up" if side == "LONG" else "down")
        return {
            "pair": pair, "side": side, "price": price,
            "zone": (z_lo, z_hi, z_type), "sl": sl_px, "tp": tp,
            "pips_tp": round(pip_tp, 1), "pips_sl": round(pip_sl, 1),
            "rr": round(rr, 2), "score": score,
            "sweep": sweep_lvl, "bias": bias, "pos": round(pos, 1),
            "flow": flow, "reasons": reasons,
        }
    return None


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def fmt_px(pair, px):
    if "JPY" in pair:
        return f"{px:,.3f}"
    return f"{px:,.5f}"


def unit(pair):
    return "$" if pair == "XAUUSD" else "pips"


def print_signal(s, cfg):
    u = unit(s["pair"])
    star = "★" if s["score"] >= 80 else ("●" if s["score"] >= cfg["min_score"] else "·")
    print(f"\n{star} {s['pair']} {s['side']}  —  QUALITY {s['score']}/100")
    print(f"   price {fmt_px(s['pair'], s['price'])}   zone "
          f"[{fmt_px(s['pair'], s['zone'][0])} – {fmt_px(s['pair'], s['zone'][1])}] ({s['zone'][2]})")
    print(f"   SL {fmt_px(s['pair'], s['sl'])}  ({s['pips_sl']} {u})   "
          f"TP {fmt_px(s['pair'], s['tp'])}  ({s['pips_tp']} {u})   R:R {s['rr']}")
    if s["sweep"]:
        sw = f"liq swept @ {s['sweep']:.5f} + reclaimed"
    else:
        sw = "no recent sweep"
    print(f"   liquidity: {sw} | flow {s['flow']} | HTF {s['bias']} | deal pos {s['pos']}%")
    print(f"   why: " + " · ".join(s["reasons"]))


def push_supabase(sig, cfg):
    """Push a signal to Supabase (PostgREST). Uses the service-role key so the
    dashboard can stay read-only. Returns a short status string."""
    url = cfg.get("supabase_url")
    key = cfg.get("supabase_key")
    if not url or not key:
        return "skip"

    endpoint = url.rstrip("/") + "/rest/v1/signals"
    payload = {
        "signal_key": f"{sig['pair']}|{sig['side']}|{sig['sl']:.5f}|{sig['tp']:.5f}",
        "pair": sig["pair"],
        "side": sig["side"],
        "price": sig["price"],
        "zone_lo": sig["zone"][0],
        "zone_hi": sig["zone"][1],
        "zone_type": sig["zone"][2],
        "sl": sig["sl"],
        "tp": sig["tp"],
        "pips_tp": sig["pips_tp"],
        "pips_sl": sig["pips_sl"],
        "rr": sig["rr"],
        "score": sig["score"],
        "sweep_level": sig["sweep"],
        "htf_bias": sig["bias"],
        "deal_pos": sig["pos"],
        "reasons": sig["reasons"],
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return "ok"
    except urllib.error.HTTPError as e:
        if e.code == 409:            # unique violation -> already stored
            return "dup"
        return f"http {e.code}"
    except Exception as e:
        return f"err {e}"


def run(cfg, seen):
    now = dt.datetime.now()
    print(f"\n=== SMC scan {now.strftime('%Y-%m-%d %H:%M:%S %Z')} "
          f"(min {cfg['min_pips']} pips, score >= {cfg['min_score']}) ===")
    found = 0
    for pair in cfg["pairs"]:
        sym, pip = INSTRUMENTS[pair]
        cfg["pip"] = pip
        try:
            rows15 = fetch(sym, "15m", "10d")
            rows1h = fetch(sym, "1h", "60d")
        except Exception as e:
            print(f"   {pair}: data error ({e})")
            continue
        s = evaluate(pair, rows15, rows1h, cfg)
        if s is None:
            continue
        sig = f"{pair}{s['side']}{round(s['sl'], 5)}{round(s['tp'], 5)}"
        if sig in seen:
            continue
        if s["score"] >= cfg["min_score"]:
            seen.add(sig)
            print_signal(s, cfg)
            res = push_supabase(s, cfg)
            if res not in ("ok", "skip"):
                print(f"   [supabase: {res}]")
            found += 1
        elif cfg["verbose"]:
            print(f"   ~ {pair} {s['side']} score {s['score']}/100 "
                  f"(below threshold) R:R {s['rr']} tp {s['pips_tp']} pips")
    if found == 0:
        print("   no qualifying setups right now — patience beats force.")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=DEFAULT_PAIRS)
    ap.add_argument("--min-pips", type=float, default=20.0)
    ap.add_argument("--min-score", type=int, default=70)
    ap.add_argument("--rr-min", type=float, default=1.5)
    ap.add_argument("--eq-pips", type=float, default=3.0)
    ap.add_argument("--sl-buffer", type=float, default=1.0)
    ap.add_argument("--min-sl-pips", type=float, default=5.0)
    ap.add_argument("--swing-n", type=int, default=2)
    ap.add_argument("--sweep-lookback", type=int, default=8)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--supabase-url", default=None, help="Supabase project URL")
    ap.add_argument("--supabase-key", default=None, help="Supabase service-role key")
    args = ap.parse_args()

    cfg = {
        "pairs": args.pairs, "min_pips": args.min_pips, "min_score": args.min_score,
        "rr_min": args.rr_min, "eq_pips": args.eq_pips, "sl_buffer": args.sl_buffer,
        "min_sl_pips": args.min_sl_pips,
        "swing_n": args.swing_n, "sweep_lookback": args.sweep_lookback,
        "verbose": args.verbose,
        "supabase_url": args.supabase_url or os.environ.get("SUPABASE_URL"),
        "supabase_key": args.supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    }
    seen = set()
    for i in range(args.repeat):
        if i > 0:
            time.sleep(args.interval)
        run(cfg, seen)
        if i < args.repeat - 1 and args.interval > 0:
            print(f"\n(next scan in {args.interval}s…)")


if __name__ == "__main__":
    main()
