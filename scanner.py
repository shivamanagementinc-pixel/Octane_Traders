#!/usr/bin/env python3
"""
SMC + Liquidity confluence scanner  (forex / gold)

Finds tradeable setups that pass BOTH filters:
  1. pip potential to the next liquidity pool >= MIN_PIPS          (default 20)
  2. SMC confluence quality score in [MIN_SCORE, MAX_SCORE)        (default 70–89)

The 70–89 band + a 4-pair universe (EURUSD, AUDUSD, XAUUSD, USDJPY) is a
data-driven choice: a 60-day backtest showed this slice wins ~35% at R:R≥1.5
for ≈ +0.40R/trade, while the 90+ "chase zone" and the noisy crosses lose.

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
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

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

# Default universe — the 4 pairs that showed a real edge in the 60-day backtest
# (score 70–89 on these = +0.40R/trade). Override with --pairs to scan more.
DEFAULT_PAIRS = ["EURUSD", "AUDUSD", "XAUUSD", "USDJPY"]

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


def telegram_text(sig):
    u = "$" if sig["pair"] == "XAUUSD" else "pips"
    return (
        f"\U0001F6A8 {sig['pair']} {sig['side']} — quality {sig['score']}/100\n"
        f"Entry {sig['price']:.5f} | SL {sig['sl']:.5f} | TP {sig['tp']:.5f}\n"
        f"Target +{sig['pips_tp']} {u} | R:R {sig['rr']} | HTF {sig['bias']}\n"
        f"Liquidity: {sig['flow']}\n"
        + " · ".join(sig["reasons"][:4])
    )


def send_telegram(text, cfg):
    """Send a Telegram message. Returns 'skip' when not configured."""
    token = cfg.get("telegram_token")
    chat_id = cfg.get("telegram_chat_id")
    if not token or not chat_id:
        return "skip"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return "ok"
    except Exception as e:
        return f"err {e}"


def close_out_signals(cfg):
    """Auto-resolve open signals: fetch open rows from Supabase, compare the
    latest price against TP/SL, and mark hit_tp / hit_sl accordingly. Also
    notifies Telegram. Runs once per scan (so outcomes lag by ≤ the cron
    interval). Fails silently when Supabase isn't configured."""
    url = cfg.get("supabase_url")
    key = cfg.get("supabase_key")
    if not url or not key:
        return
    base = url.rstrip("/") + "/rest/v1"
    req = urllib.request.Request(
        f"{base}/signals?status=eq.open&select=id,pair,side,tp,sl",
        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"   [close-out] fetch error: {e}")
        return
    changed = 0
    for row in rows:
        pair = row.get("pair")
        side = row.get("side")
        info = INSTRUMENTS.get(pair)
        if not info:
            continue
        try:
            last = fetch(info[0], "5m", "1d")[-1][4]
        except Exception:
            continue
        try:
            tp = float(row["tp"])
            sl = float(row["sl"])
        except (TypeError, ValueError):
            continue
        new = None
        if side == "LONG":
            if last >= tp:
                new = "hit_tp"
            elif last <= sl:
                new = "hit_sl"
        elif side == "SHORT":
            if last <= tp:
                new = "hit_tp"
            elif last >= sl:
                new = "hit_sl"
        if not new:
            continue
        patch = urllib.request.Request(
            f"{base}/signals?id=eq.{row['id']}",
            data=json.dumps({"status": new}).encode(),
            method="PATCH",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            with urllib.request.urlopen(patch, timeout=15):
                pass
            changed += 1
            print(f"   [close-out] {pair} {side} -> {new}")
            send_telegram(f"\u2705 {pair} {side}: {new.replace('_', ' ').upper()} (TP {tp:.5f} / SL {sl:.5f})", cfg)
        except Exception as e:
            print(f"   [close-out] update error: {e}")
    if changed:
        print(f"   [close-out] {changed} open signal(s) resolved")


def in_blackout(cfg):
    """True during the daily high-spread window (e.g. the 5pm–6:30pm rollover).
    Signals inside it are treated as noise: not recorded, not alerted, and no
    close-out marking happens (so fake TP/SL wicks can't corrupt results)."""
    if not cfg.get("blackout"):
        return False
    start = cfg.get("blackout_start")
    end = cfg.get("blackout_end")
    if not start or not end:
        return False
    try:
        tz = ZoneInfo(cfg.get("blackout_tz", "America/Toronto"))
    except Exception:
        return False
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except Exception:
        return False
    now = dt.datetime.now(tz)
    s = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    e = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if e <= s:                     # window crosses midnight
        return now >= s or now < e
    return s <= now < e


def telegram_test(cfg):
    """Send a one-off test message (used by the Telegram Test workflow)."""
    token = cfg.get("telegram_token")
    chat = cfg.get("telegram_chat_id")
    if not token or not chat:
        print("   telegram not configured (missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r = send_telegram(f"\u2705 SMC scanner online — test message {stamp}", cfg)
    print(f"   telegram test -> {r}")


def telegram_demo(cfg):
    """Send a realistic DEMO signal message (same format as a real alert) so
    you can verify the full signal->Telegram path without waiting for a real
    setup. Does NOT write anything to Supabase."""
    token = cfg.get("telegram_token")
    chat = cfg.get("telegram_chat_id")
    if not token or not chat:
        print("   telegram not configured (missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return
    sig = {
        "pair": "EURUSD", "side": "LONG", "score": 83,
        "price": 1.1582, "sl": 1.1562, "tp": 1.1623,
        "pips_tp": 41.0, "rr": 2.1, "bias": "bull", "flow": "up",
        "reasons": ["HTF(1H) bullish", "sell-side liq swept + reclaim",
                    "inside Order Block", "inside FVG", "R:R 2.05"],
    }
    r = send_telegram(telegram_text(sig) + "\n\n⚠️ DEMO SIGNAL — not a real setup", cfg)
    print(f"   telegram demo signal -> {r}")


def resend_telegram(cfg):
    """Honour dashboard 'resend' requests: rows with resend=true are re-sent to
    Telegram and the flag is cleared. Runs on each scan (so lag ≤ cron interval,
    or instantly if you trigger the workflow manually)."""
    url = cfg.get("supabase_url")
    key = cfg.get("supabase_key")
    if not url or not key:
        return
    base = url.rstrip("/") + "/rest/v1"
    req = urllib.request.Request(
        f"{base}/signals?resend=eq.true&select=*",
        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"   [resend] fetch error: {e}")
        return
    for row in rows:
        strat = row.get("strategy") or "smc"
        pair, side = row["pair"], row["side"]
        if strat == "scalp":
            text = (
                "\U0001F504 RESEND\n"
                f"\U0001F3AF {pair} {side} — SCALP (target {row.get('rr')}R)\n"
                f"Entry {row.get('price')} | SL {row.get('sl')} | TP {row.get('tp')}\n"
                f"5m momentum pullback · {row.get('htf_bias') or '?'} trend"
            )
        else:
            sig = {
                "pair": pair, "side": side, "score": row.get("score"),
                "price": float(row["price"]), "sl": float(row["sl"]),
                "tp": float(row["tp"]), "pips_tp": float(row["pips_tp"]),
                "rr": float(row["rr"]), "bias": row.get("htf_bias"),
                "flow": "up" if side == "LONG" else "down",
                "reasons": row.get("reasons") or [],
            }
            text = "\U0001F504 RESEND\n" + telegram_text(sig)
        t = send_telegram(text, cfg)
        print(f"   [resend] {pair} {side} ({strat}) -> telegram {t}")
        patch = urllib.request.Request(
            f"{base}/signals?id=eq.{row['id']}",
            data=json.dumps({"resend": False}).encode(),
            method="PATCH",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            with urllib.request.urlopen(patch, timeout=15):
                pass
        except Exception as e:
            print(f"   [resend] clear error: {e}")


def recently_signaled(cfg, pair, side, hours):
    """True if a signal for the same pair+side was recorded within the last
    `hours` (used as a Telegram cooldown, so a persistent setup doesn't ping
    you every scan). Falls back to no-op when Supabase isn't configured."""
    url = cfg.get("supabase_url")
    key = cfg.get("supabase_key")
    if not url or not key or not hours:
        return False
    base = url.rstrip("/") + "/rest/v1"
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours))
    since_iso = since.isoformat().replace("+00:00", "Z")
    q = (f"{base}/signals?pair=eq.{urllib.parse.quote(pair)}"
         f"&side=eq.{side}&created_at=gte.{since_iso}&select=id&limit=1")
    req = urllib.request.Request(q, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
        return bool(rows)
    except Exception:
        return False


def in_session(cfg):
    """True when 'now' is inside the active trading-hours window (default
    London+NY: 03:00–17:00 America/Toronto). Outside it, the tape is mostly
    Asian chop / late-NY drift — the backtest showed filtering to these hours
    roughly doubles expectancy."""
    if not cfg.get("session_filter"):
        return True
    start = cfg.get("session_start")
    end = cfg.get("session_end")
    if not start or not end:
        return True
    try:
        tz = ZoneInfo(cfg.get("session_tz", "America/Toronto"))
    except Exception:
        return True
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except Exception:
        return True
    now = dt.datetime.now(tz)
    s = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    e = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if e <= s:
        return now >= s or now < e
    return s <= now < e


def run(cfg, seen):
    now = dt.datetime.now()
    print(f"\n=== SMC scan {now.strftime('%Y-%m-%d %H:%M:%S %Z')} "
          f"(min {cfg['min_pips']} pips, score {cfg['min_score']}-{cfg['max_score']}) ===")
    # Housekeeping ALWAYS runs (every 5 min), even outside trading hours —
    # otherwise dashboard resend requests and TP/SL tracking would stall all
    # evening. Only NEW-signal scanning is gated by session/blackout below.
    close_out_signals(cfg)
    resend_telegram(cfg)
    if in_blackout(cfg):
        print(f"   [blackout] {cfg['blackout_start']}–{cfg['blackout_end']} "
              f"{cfg.get('blackout_tz', '')} — no new signals (high-spread window)")
        return 0
    if not in_session(cfg):
        print(f"   [session] outside {cfg.get('session_start')}–{cfg.get('session_end')} "
              f"{cfg.get('session_tz', '')} — no new signals (off-hours chop)")
        return 0
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
        # score ceiling: the 90+ bucket is a "chase" zone that lost money in
        # backtesting — drop it (default max_score=89).
        if s["score"] >= cfg["max_score"]:
            if cfg["verbose"]:
                print(f"   ~ {pair} {s['side']} score {s['score']} (>= max {cfg['max_score']}, "
                      f"chase zone — skipped)")
            continue
        # bias alignment: only trade WITH the 1H trend (backtest: +0.19R -> +0.41R)
        if cfg["require_bias"]:
            aligned = ((s["side"] == "LONG" and s["bias"] == "bull")
                       or (s["side"] == "SHORT" and s["bias"] == "bear"))
            if not aligned:
                if cfg["verbose"]:
                    print(f"   ~ {pair} {s['side']} skipped (bias {s['bias']} disagrees)")
                continue
        if s["score"] >= cfg["min_score"]:
            seen.add(sig)
            # Telegram cooldown: only ping if this pair+side hasn't been alerted
            # recently (recording still happens — every signal feeds the report).
            fresh = not recently_signaled(cfg, s["pair"], s["side"], cfg["telegram_cooldown_hours"])
            print_signal(s, cfg)
            res = push_supabase(s, cfg)
            if res not in ("ok", "skip"):
                print(f"   [supabase: {res}]")
            if res in ("ok", "skip") and fresh:
                t = send_telegram(telegram_text(s), cfg)
                if t not in ("ok", "skip"):
                    print(f"   [telegram: {t}]")
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
    ap.add_argument("--max-score", type=int, default=89,
                    help="Score ceiling — drop signals at/above this (90+ = chase zone). Default 89.")
    ap.add_argument("--telegram-cooldown-hours", type=float, default=1.0,
                    help="Min hours between Telegram pings for the same pair+side. Default 1.")
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
    ap.add_argument("--telegram-token", default=None, help="Telegram bot token")
    ap.add_argument("--telegram-chat-id", default=None, help="Telegram chat id")
    ap.add_argument("--telegram-test", action="store_true",
                    help="Send a Telegram test message and exit")
    ap.add_argument("--telegram-demo", action="store_true",
                    help="Send a realistic DEMO signal to Telegram and exit")
    ap.add_argument("--blackout-start", default="17:00",
                    help="Daily blackout start HH:MM (default 17:00)")
    ap.add_argument("--blackout-end", default="18:30",
                    help="Daily blackout end HH:MM (default 18:30)")
    ap.add_argument("--blackout-tz", default="America/Toronto",
                    help="IANA timezone for the blackout window")
    ap.add_argument("--no-blackout", action="store_true",
                    help="Disable the blackout window")
    ap.add_argument("--no-bias-filter", action="store_true",
                    help="Allow counter-trend signals (default: trade WITH the 1H trend)")
    ap.add_argument("--session-start", default="03:00",
                    help="Active-hours start HH:MM (default 03:00 = London open ET)")
    ap.add_argument("--session-end", default="17:00",
                    help="Active-hours end HH:MM (default 17:00 = NY close ET)")
    ap.add_argument("--session-tz", default="America/Toronto",
                    help="IANA timezone for active-hours window")
    ap.add_argument("--no-session-filter", action="store_true",
                    help="Disable the active-hours filter (scan 24/5)")
    args = ap.parse_args()

    cfg = {
        "pairs": args.pairs, "min_pips": args.min_pips, "min_score": args.min_score,
        "max_score": args.max_score, "telegram_cooldown_hours": args.telegram_cooldown_hours,
        "rr_min": args.rr_min, "eq_pips": args.eq_pips, "sl_buffer": args.sl_buffer,
        "min_sl_pips": args.min_sl_pips,
        "swing_n": args.swing_n, "sweep_lookback": args.sweep_lookback,
        "verbose": args.verbose,
        "supabase_url": args.supabase_url or os.environ.get("SUPABASE_URL"),
        "supabase_key": args.supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "telegram_token": args.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": args.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID"),
        "blackout": not args.no_blackout,
        "blackout_start": args.blackout_start,
        "blackout_end": args.blackout_end,
        "blackout_tz": args.blackout_tz,
        "require_bias": not args.no_bias_filter,
        "session_filter": not args.no_session_filter,
        "session_start": args.session_start,
        "session_end": args.session_end,
        "session_tz": args.session_tz,
    }
    if args.telegram_test:
        telegram_test(cfg)
        return
    if args.telegram_demo:
        telegram_demo(cfg)
        return
    seen = set()
    for i in range(args.repeat):
        if i > 0:
            time.sleep(args.interval)
        run(cfg, seen)
        if i < args.repeat - 1 and args.interval > 0:
            print(f"\n(next scan in {args.interval}s…)")


if __name__ == "__main__":
    main()
