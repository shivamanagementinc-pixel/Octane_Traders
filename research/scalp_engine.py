#!/usr/bin/env python3
"""
Octane Traders — Aggressive Scalp Engine (1m/5m, high-liquidity FX + indices)

Different philosophy from the main SMC swing system:
  - HIGH win rate, SMALL targets (1R default, 1.5R optional)
  - trend-following momentum pullbacks on the 5m, in the 15m trend direction
  - session-filtered to London/NY (high liquidity)

Backtested (60 days, 5m, 8 assets, London/NY hours):
    1R  target → 60.9% win rate, +0.22R/trade
    1.5R target → 53.3% win rate, +0.33R/trade

Modes
-----
  python3 scalp_engine.py                    # live scan + push to Supabase/Telegram
  python3 scalp_engine.py --backtest         # 60-day walk-forward backtest
  python3 scalp_engine.py --tp-atr 1.0       # 1R target (more wins)
  python3 scalp_engine.py --tp-atr 1.5       # 1.5R target (more per win)

Stdlib only — no dependencies.
"""

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0"}

ASSETS = {
    "EURUSD": ("EURUSD=X", 0.0001),
    "GBPUSD": ("GBPUSD=X", 0.0001),
    "USDJPY": ("JPY=X", 0.01),
    "AUDUSD": ("AUDUSD=X", 0.0001),
    "USDCAD": ("CAD=X", 0.0001),
    "SPX500": ("ES=F", 1.0),
    "NAS100": ("NQ=F", 1.0),
    "US30":  ("YM=F", 1.0),
}

RSI_N = 14
RSI_BUY = 38.0
RSI_SELL = 62.0
ATR_N = 14
SL_ATR = 1.0
TP_ATR = 1.5        # default 1.5R (backtested best net of costs)
MIN_PIPS_FX = 5.0   # skip FX signals whose target is under this many pips
MIN_PTS_IDX = 30.0  # skip index signals whose target is under this many points
MAX_HOLD = 24
SESSION = [(3, 17)]


def fetch(sym, interval, rng):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range={rng}&interval={interval}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        rows.append((t, float(o), float(h), float(l), float(c)))
    return rows


def ema(vals, n):
    k = 2/(n+1); e = vals[0]; out = [e]
    for v in vals[1:]:
        e = v*k + e*(1-k); out.append(e)
    return out


def rsi(closes, n=14):
    if len(closes) < n+1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i]-closes[i-1]
        gains.append(max(ch,0)); losses.append(max(-ch,0))
    ag = sum(gains[-n:])/n; al = sum(losses[-n:])/n
    if al == 0: return 100.0
    return 100 - 100/(1+ag/al)


def atr(rows, n=14):
    trs = []
    for i in range(1, len(rows)):
        _,o,h,l,c = rows[i]; pc = rows[i-1][4]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-n:])/n if len(trs) >= n else 0.0


def bias_15m(rows15):
    closes = [r[4] for r in rows15]
    if len(closes) < 60: return "flat", 0.0
    e9, e21 = ema(closes,9), ema(closes,21)
    if e9[-1] > e21[-1] and closes[-1] > e21[-1]: return "up", (e9[-1]-e21[-1])/e21[-1]
    if e9[-1] < e21[-1] and closes[-1] < e21[-1]: return "down", (e21[-1]-e9[-1])/e21[-1]
    return "flat", 0.0


def in_session(ts, tz, sessions):
    hh = dt.datetime.fromtimestamp(ts, tz).hour
    return any(lo <= hh < hi for lo, hi in sessions)


def signal(asset, rows15, rows5, cfg):
    if len(rows5) < ATR_N + 2: return None
    bdir, _ = bias_15m(rows15)
    if bdir == "flat": return None
    c5 = [r[4] for r in rows5]
    r = rsi(c5, RSI_N)
    a = atr(rows5, ATR_N)
    if a <= 0: return None
    price = rows5[-1][4]
    if bdir == "up" and r < cfg["rsi_buy"]:
        side = "LONG"; sl = price - cfg["sl_atr"]*a; tp = price + cfg["tp_atr"]*a
    elif bdir == "down" and r > cfg["rsi_sell"]:
        side = "SHORT"; sl = price + cfg["sl_atr"]*a; tp = price - cfg["tp_atr"]*a
    else:
        return None
    if sl <= 0 or tp <= 0: return None
    # Convert to PIPS (not raw price units) — the Supabase column is
    # numeric(10,2), so raw units like 0.00044 would round to 0.00.
    pip_size = ASSETS[asset][1]
    pips_sl = abs(price - sl) / pip_size
    pips_tp = abs(price - tp) / pip_size
    # minimum-target filter: a 1-2 pip target is smaller than the round-trip
    # spread/commission cost, so it's unwinnable net. Skip those.
    is_idx = asset in ("SPX500", "NAS100", "US30")
    min_target = cfg.get("min_pts_idx", MIN_PTS_IDX) if is_idx else cfg.get("min_pips_fx", MIN_PIPS_FX)
    if pips_tp < min_target:
        return None
    return {
        "asset": asset, "side": side, "price": price, "sl": sl, "tp": tp,
        "rsi": round(r,1), "atr": round(a,5), "bias": bdir,
        "rr": round(cfg["tp_atr"]/cfg["sl_atr"],2),
        "pips_sl": round(pips_sl, 1), "pips_tp": round(pips_tp, 1),
        "ts": rows5[-1][0],
    }


def outcome(s, rows5, idx):
    for j in range(idx+1, min(idx+1+MAX_HOLD, len(rows5))):
        h, l = rows5[j][2], rows5[j][3]
        hit_sl = (s["side"]=="LONG" and l <= s["sl"]) or (s["side"]=="SHORT" and h >= s["sl"])
        hit_tp = (s["side"]=="LONG" and h >= s["tp"]) or (s["side"]=="SHORT" and l <= s["tp"])
        if hit_sl and hit_tp: return "loss"
        if hit_sl: return "loss"
        if hit_tp: return "win"
    return "open"


# ---------------------------------------------------------------- backtest
def backtest(cfg):
    tz = ZoneInfo("America/Toronto")
    print(f"=== SCALP BACKTEST — 5m, 60d, TP={cfg['tp_atr']}×ATR SL={cfg['sl_atr']}×ATR "
          f"RSI<{cfg['rsi_buy']}/>{cfg['rsi_sell']}, London/NY ===\n")
    rows_all = {}
    for asset in ASSETS:
        sym,_ = ASSETS[asset]
        try: rows_all[asset] = fetch(sym, "5m", "60d")
        except Exception as e: print(f"  {asset}: {e}")
    trades = []
    for asset, rows5 in rows_all.items():
        sym,_ = ASSETS[asset]
        try: rows15 = fetch(sym, "15m", "60d")
        except Exception: continue
        in_trade = None
        for i in range(ATR_N+2, len(rows5)):
            ts = rows5[i][0]
            if in_trade is not None:
                o = outcome(in_trade[1], rows5, in_trade[0])
                if o == "open": continue
                trades.append((asset, in_trade[1]["side"], o, in_trade[1]["rr"]))
                in_trade = None
                continue
            if not in_session(ts, tz, cfg["sessions"]): continue
            r15 = [r for r in rows15 if r[0] <= ts]
            if len(r15) < 60: continue
            s = signal(asset, r15[-120:], rows5[max(0,i-80):i+1], cfg)
            if s: in_trade = (i, s)
    if not trades:
        print("  no trades"); return
    n = len(trades); w = sum(1 for t in trades if t[2]=="win"); l = n-w
    totR = sum((t[3] if t[2]=="win" else -1) for t in trades)
    exp = totR/n
    from collections import defaultdict
    per = defaultdict(lambda:[0,0])
    for t in trades: per[t[0]][0 if t[2]=="win" else 1] += 1
    print(f"trades: {n}  wins: {w}  losses: {l}")
    print(f"WIN RATE: {w/n*100:.1f}%   expectancy: {exp:+.3f}R/trade   total: {totR:+.1f}R")
    print(f"≈ {n/60:.0f} signals/day across {len(ASSETS)} assets")
    print(f"\n{'asset':8} {'n':>4} {'win%':>6} {'netR':>7}")
    for a,(ww,ll) in sorted(per.items(), key=lambda kv:-(kv[1][0]+kv[1][1])):
        nn = ww+ll; net = ww*cfg['tp_atr']/cfg['sl_atr'] - ll
        print(f"{a:8} {nn:4} {ww/nn*100:6.1f} {net:7.1f}")


# ------------------------------------------------------------- supabase
def push_supabase(s, cfg):
    url, key = cfg.get("supabase_url"), cfg.get("supabase_key")
    if not url or not key: return "skip"
    endpoint = url.rstrip("/") + "/rest/v1/signals"
    payload = {
        "signal_key": f"scalp|{s['asset']}|{s['side']}|{s['sl']:.5f}|{s['tp']:.5f}",
        "strategy": "scalp",
        "pair": s["asset"], "side": s["side"], "price": s["price"],
        "zone_lo": s["sl"], "zone_hi": s["tp"], "zone_type": "ATR",
        "sl": s["sl"], "tp": s["tp"],
        "pips_tp": s["pips_tp"], "pips_sl": s["pips_sl"], "rr": s["rr"],
        "score": None, "sweep_level": None, "htf_bias": s["bias"],
        "deal_pos": s["rsi"],
        "reasons": [f"5m RSI {s['rsi']}", f"{s['bias']} 15m trend", "momentum pullback"],
    }
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
        method="POST", headers={"apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=15): return "ok"
    except urllib.error.HTTPError as e:
        return "dup" if e.code == 409 else f"http {e.code}"
    except Exception as e:
        return f"err {e}"


def telegram_text(s):
    u = "pts" if s["asset"] in ("SPX500","NAS100","US30") else "pips"
    return (f"\U0001F3AF {s['asset']} {s['side']} — SCALP (target {s['rr']}R)\n"
            f"Entry {s['price']:.5f} | SL {s['sl']:.5f} | TP {s['tp']:.5f}\n"
            f"5m RSI {s['rsi']} · {s['bias']} 15m trend · {s['pips_tp']} {u} target")


def send_telegram(text, cfg):
    token, chat = cfg.get("telegram_token"), cfg.get("telegram_chat_id")
    if not token or not chat: return "skip"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=15):
            return "ok"
    except Exception as e:
        return f"err {e}"


def close_out(cfg):
    """Auto-resolve open scalp signals (strategy='scalp').

    Checks the intrabar high/low of every 5m bar SINCE the signal was created —
    not just the latest close — so a trade whose TP/SL was touched hours ago
    and then retraced is still marked correctly (conservative: SL wins on a
    bar where both are touched)."""
    url, key = cfg.get("supabase_url"), cfg.get("supabase_key")
    if not url or not key: return
    base = url.rstrip("/") + "/rest/v1"
    # NOTE: no strategy filter here — older rows may predate the strategy
    # column, so we filter by pair-set membership instead (robust).
    req = urllib.request.Request(
        f"{base}/signals?status=eq.open&select=id,pair,side,tp,sl,created_at",
        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"   [close-out] {e}"); return
    rows = [r for r in rows if r.get("pair") in ASSETS]
    print(f"   [close-out] checking {len(rows)} open scalp row(s)")
    for row in rows:
        sym = ASSETS.get(row["pair"], (None,))[0]
        if not sym: continue
        try:
            bars = fetch(sym, "5m", "5d")
        except Exception:
            continue
        tp, sl = float(row["tp"]), float(row["sl"])
        # only bars strictly after the signal's creation time
        try:
            created = row.get("created_at")
            created_ts = dt.datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
        except Exception:
            created_ts = 0.0
        new = None
        for t, o, h, l, c in bars:
            if t <= created_ts:
                continue
            if row["side"] == "LONG":
                hit_sl = l <= sl
                hit_tp = h >= tp
            else:
                hit_sl = h >= sl
                hit_tp = l <= tp
            if hit_sl and hit_tp:
                new = "hit_sl"          # conservative: stop assumed filled first
                break
            if hit_sl:
                new = "hit_sl"; break
            if hit_tp:
                new = "hit_tp"; break
        if not new: continue
        patch = urllib.request.Request(f"{base}/signals?id=eq.{row['id']}",
            data=json.dumps({"status": new}).encode(), method="PATCH",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            with urllib.request.urlopen(patch, timeout=15): pass
            print(f"   [close-out] {row['pair']} {row['side']} -> {new}")
            # Telegram alert is sent instantly by the Edge Function (DB trigger).
        except Exception as e:
            print(f"   [close-out] err {e}")


def live_scan(cfg):
    tz = ZoneInfo("America/Toronto")
    now = dt.datetime.now(tz)
    # Housekeeping always runs: auto-close-out of open scalp signals must keep
    # tracking TP/SL 24/5, even when new-signal scanning is paused.
    close_out(cfg)
    if not any(lo <= now.hour < hi for lo, hi in cfg["sessions"]):
        print(f"   [session] outside {cfg['sessions']} ET — no new scalp signals (low liquidity)")
        return 0
    print(f"=== SCALP SCAN {now.strftime('%Y-%m-%d %H:%M:%S %Z')} (TP={cfg['tp_atr']}R) ===")
    found = 0
    for asset in ASSETS:
        sym,_ = ASSETS[asset]
        try:
            rows15 = fetch(sym, "15m", "10d")
            rows5  = fetch(sym, "5m", "5d")
            s = signal(asset, rows15[-120:], rows5[-80:], cfg)
        except Exception as e:
            print(f"   {asset}: {e}"); continue
        if not s: continue
        print(f"   {s['asset']} {s['side']} {s['price']:.5f} SL {s['sl']:.5f} TP {s['tp']:.5f} "
              f"R:R {s['rr']} RSI {s['rsi']} ({s['bias']})")
        res = push_supabase(s, cfg)
        if res not in ("ok","skip"): print(f"   [supabase: {res}]")
        # Telegram alert is sent instantly by the Edge Function (DB trigger).
        found += 1
    if not found: print("   no scalp signals right now")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--tp-atr", type=float, default=TP_ATR)
    ap.add_argument("--sl-atr", type=float, default=SL_ATR)
    ap.add_argument("--rsi-buy", type=float, default=RSI_BUY)
    ap.add_argument("--rsi-sell", type=float, default=RSI_SELL)
    ap.add_argument("--min-pips-fx", type=float, default=MIN_PIPS_FX,
                    help="skip FX signals with a target under this many pips")
    ap.add_argument("--min-pts-idx", type=float, default=MIN_PTS_IDX,
                    help="skip index signals with a target under this many points")
    args = ap.parse_args()
    cfg = {"tp_atr": args.tp_atr, "sl_atr": args.sl_atr,
           "rsi_buy": args.rsi_buy, "rsi_sell": args.rsi_sell,
           "min_pips_fx": args.min_pips_fx, "min_pts_idx": args.min_pts_idx,
           "sessions": SESSION,
           "supabase_url": os.environ.get("SUPABASE_URL"),
           "supabase_key": os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
           "telegram_token": os.environ.get("TELEGRAM_BOT_TOKEN"),
           "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID")}
    if args.backtest:
        backtest(cfg)
    else:
        live_scan(cfg)


if __name__ == "__main__":
    main()
