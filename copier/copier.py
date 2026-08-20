#!/usr/bin/env python3
"""
Octane Traders — Stage 1 trade copier (Python + MetaTrader5 on your VPS).

What it does (loop, every ~15s):
  1. reads the master kill-switch + active accounts from Supabase
  2. picks up NEW signals and, for each active account, computes the lot size
     from that account's risk % and places the order on its MT5 account
  3. records the position in Supabase (admin dashboard sees it live)
  4. processes admin commands (close a position / close all)
  5. reconciles closed positions (marks closed_win / closed_loss)

Run it 24/7 on a small VPS that has MT5 installed and is logged in.

Usage:
  export SUPABASE_URL=https://YOUR-REF.supabase.co
  export SUPABASE_SERVICE_ROLE_KEY=sb_secret_...
  python3 copier.py            # foreground
  python3 copier.py --once     # single pass (good for testing)

Requires: pip install MetaTrader5 requests
"""

import argparse
import configparser
import json
import os
import sys
import time
import datetime as dt
import urllib.request

try:
    from zoneinfo import ZoneInfo
except ImportError:           # Python < 3.9
    ZoneInfo = None

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from config import SYMBOL_MAP, MAGIC, DEFAULT_RISK_PCT, USD_PER_UNIT_LOT as _BUILTIN_UNITS
from lot_calculator import size_lots

# ------------------------------------------------------------------ config
def _app_dir():
    if getattr(sys, "frozen", False):        # running as a PyInstaller .exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Allow runtime overrides without rebuilding the exe: if a config_local.py
# sits next to the exe, its SYMBOL_MAP / USD_PER_UNIT_LOT etc. win.
try:
    import importlib.util as _ilu
    _lp = os.path.join(_app_dir(), "config_local.py")
    if os.path.exists(_lp):
        _spec = _ilu.spec_from_file_location("config_local", _lp)
        _mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
        for _name in ("SYMBOL_MAP", "USD_PER_UNIT_LOT", "MAGIC",
                      "MIN_LOT", "MAX_LOT", "LOT_STEP", "DEFAULT_RISK_PCT"):
            if hasattr(_mod, _name):
                globals()[_name] = getattr(_mod, _name)
except Exception:
    pass


def _load_ini():
    """Read copier.ini (same folder as the exe/script). Env vars take priority."""
    ini = {}
    p = os.path.join(_app_dir(), "copier.ini")
    if os.path.exists(p):
        cp = configparser.ConfigParser()
        cp.read(p)
        if cp.has_section("copier"):
            ini = dict(cp.items("copier"))
    return ini

INI = _load_ini()

def _cfg(key):
    return os.environ.get(key) or INI.get(key.lower()) or ""

SUPABASE_URL = _cfg("SUPABASE_URL")
SUPABASE_KEY = _cfg("SUPABASE_SERVICE_ROLE_KEY")

# Trading-hours guard (mirrors the scanner): only OPEN new trades inside
# London/NY hours and outside the 5pm rollover blackout. Close commands and
# reconciliation always run.
SESSION_HOURS = [(3, 17)]      # ET hours
BLACKOUT = ("17:00", "18:30")  # ET
IGNORE_HOURS = False           # set by --ignore-hours CLI flag


def _tz():
    """America/Toronto tz, with a Windows fallback (zoneinfo needs tzdata)."""
    tzname = os.environ.get("COPIEUR_TZ") or INI.get("timezone") or "America/Toronto"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tzname)
        except Exception:
            pass
    print(f"   [warn] timezone database missing — using UTC-4 fallback.")
    return dt.timezone(dt.timedelta(hours=-4))


TRADE_TZ = _tz()


def trading_allowed():
    now = dt.datetime.now(TRADE_TZ)
    for lo, hi in SESSION_HOURS:
        if lo <= now.hour < hi:
            sh, sm = (int(x) for x in BLACKOUT[0].split(":"))
            eh, em = (int(x) for x in BLACKOUT[1].split(":"))
            s = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
            e = now.replace(hour=eh, minute=em, second=0, microsecond=0)
            if e <= s:
                return not (now >= s or now < e)
            return not (s <= now < e)
    return False

# ------------------------------------------------------------------ supabase
def sb(method, path, payload=None):
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path
    req = urllib.request.Request(url, method=method,
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    data = json.dumps(payload).encode() if payload is not None else None
    with urllib.request.urlopen(req, data=data, timeout=20) as r:
        return json.loads(r.read())


def sb_select(path):
    return sb("GET", path)


def sb_insert(path, payload):
    return sb("POST", path, payload)


def sb_update(path, payload):
    return sb("PATCH", path, payload)


# ------------------------------------------------------------------ mt5 glue
def mt5_account(sym_map, cred):
    """Open an MT5 session for one account. Returns symbol->actual mapping."""
    if not MT5_AVAILABLE:
        print("   [!] MetaTrader5 package not installed (pip install MetaTrader5)")
        return None
    login = int(cred["mt5_login"])
    password = cred["mt5_password"]
    server = cred.get("mt5_server") or None
    kwargs = {"login": login, "password": password}
    if server:
        kwargs["server"] = server
    if not mt5.initialize(**kwargs):
        err = mt5.last_error()
        print(f"   [!] init failed for login {login}: {err}")
        if err and err[0] == -10005:
            print("   [hint] 'IPC timeout' = the copier can't reach the MT5 terminal. Fix:")
            print("          1. Run MT5 and this exe with the SAME Windows privileges "
                  "(both as admin, or both normal)")
            print("          2. Make sure MT5 finished updating and is fully logged in")
            print("          3. Close any OTHER MT5 terminals / MetaEditor instances")
            print("          4. Restart MT5, then run this exe again")
        return None
    suffix = cred.get("symbol_suffix") or ""
    actual = {}
    for our, sym in sym_map.items():
        actual[our] = sym + suffix
    # ensure symbols are visible (Market Watch)
    for our, sym in actual.items():
        if not mt5.symbol_select(sym, True):
            print(f"   [!] symbol {sym} not available on this account")
    return actual


def place_order(actual_sym, side, volume, sl, tp, comment):
    symbol = actual_sym
    price = mt5.symbol_info_tick(symbol)
    if price is None:
        print(f"   [!] no tick for {symbol}")
        return None
    if side == "LONG":
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY,
            "price": price.ask,
            "sl": float(sl),
            "tp": float(tp),
            "magic": MAGIC,
            "comment": comment[:27],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
    else:
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_SELL,
            "price": price.bid,
            "sl": float(sl),
            "tp": float(tp),
            "magic": MAGIC,
            "comment": comment[:27],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"   [!] order failed {symbol}: {result.comment if result else mt5.last_error()}")
        return None
    return result


def close_position(ticket):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return "already_closed"
    pos = pos[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return "no_tick"
    if pos.type == mt5.POSITION_TYPE_BUY:
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": pos.ticket,
               "symbol": pos.symbol, "volume": pos.volume,
               "type": mt5.ORDER_TYPE_SELL, "price": tick.bid,
               "magic": MAGIC, "comment": "octane-close",
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_FOK}
    else:
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": pos.ticket,
               "symbol": pos.symbol, "volume": pos.volume,
               "type": mt5.ORDER_TYPE_BUY, "price": tick.ask,
               "magic": MAGIC, "comment": "octane-close",
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_FOK}
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return f"failed: {result.comment if result else mt5.last_error()}"
    return "closed"


# ------------------------------------------------------------------ main loop
def run_once(watermark):
    """One copier pass. Returns the newest signal created_at seen (watermark)."""
    # 1) master switch
    try:
        settings = sb_select("settings?key=eq.trade_enabled&select=key,value")
        enabled = settings and settings[0]["value"] is True
    except Exception as e:
        print(f"   [!] settings read failed: {e}")
        return watermark
    # optional test-mode: lets you place a demo order outside trading hours
    try:
        tm = sb_select("settings?key=eq.test_mode&select=key,value")
        test_mode = bool(tm and tm[0]["value"] is True)
    except Exception:
        test_mode = False

    # 2) active accounts + credentials (service_role reads secrets)
    try:
        accounts = sb_select("accounts?active=eq.true&select=id,name,risk_pct,is_demo")
        creds = sb_select("account_credentials?select=account_id,mt5_login,mt5_password,mt5_server,symbol_suffix")
    except Exception as e:
        print(f"   [!] accounts read failed: {e}")
        return watermark
    cred_by_acc = {c["account_id"]: c for c in creds}
    accounts = [a for a in accounts if a["id"] in cred_by_acc]

    # 3) new signals (since watermark, still open)
    try:
        wm = watermark.isoformat().replace("+00:00", "Z")
        sigs = sb_select(f"signals?status=eq.open&created_at=gt.{wm}&order=created_at.asc"
                         "&select=id,pair,side,sl,tp,pips_sl,strategy,created_at")
    except Exception as e:
        print(f"   [!] signals read failed: {e}")
        sigs = []

    # 4) already-placed signal ids per account (avoid double-entry)
    try:
        placed = sb_select("positions?status=eq.open&select=account_id,signal_id")
        placed_keys = {(p["account_id"], p["signal_id"]) for p in placed if p["signal_id"]}
    except Exception:
        placed_keys = set()

    print(f"   [copier] {len(accounts)} account(s) connected, {len(sigs)} new signal(s)")
    if not enabled:
        print(f"   [kill-switch] trading paused — processing only admin close commands")
    elif not (trading_allowed() or test_mode or IGNORE_HOURS):
        print(f"   [hours] outside trading session/blackout — not opening new trades")
    elif test_mode:
        print(f"   [test-mode] hours guard bypassed — will place demo orders")

    open_new = enabled and (trading_allowed() or test_mode or IGNORE_HOURS)

    for sig in sigs:
        our_pair = sig["pair"]
        if our_pair not in SYMBOL_MAP:
            continue
        for acc in accounts:
            if (acc["id"], sig["id"]) in placed_keys:
                continue
            if not open_new:
                continue
            # size the trade from this account's own risk %
            cred = cred_by_acc[acc["id"]]
            symbol_map = mt5_account(SYMBOL_MAP, cred)
            if symbol_map is None:
                continue
            sym = symbol_map[our_pair]
            try:
                info = mt5.account_info()
                balance = info.balance
            except Exception:
                balance = 0.0
            volume = size_lots(balance, float(acc["risk_pct"]), float(sig["pips_sl"]), our_pair,
                              unit_lookup=globals().get("USD_PER_UNIT_LOT", _BUILTIN_UNITS))
            if volume <= 0:
                print(f"   [skip] {acc['name']} {our_pair}: size=0 (stop={sig['pips_sl']})")
                mt5.shutdown()
                continue
            volume = float(volume)
            # MT5 also enforces its own min/step — snap down to it
            sym_info = mt5.symbol_info(sym)
            if sym_info is not None:
                step = sym_info.volume_step or 0.01
                vmin = sym_info.volume_min or 0.01
                vmax = sym_info.volume_max or 100.0
                import math
                volume = max(vmin, min(vmax, math.floor(volume / step) * step))
                volume = round(volume, 2)
            if volume <= 0:
                mt5.shutdown()
                continue
            print(f"   [trade] {acc['name']} {our_pair} {sig['side']} vol={volume} "
                  f"(balance={balance:.0f}, risk={acc['risk_pct']}%, stop={sig['pips_sl']})")
            res = place_order(sym, sig["side"], volume, sig["sl"], sig["tp"],
                              f"octane {our_pair} {sig['side']}")
            if res is not None and res.order > 0:
                sb_insert("positions", {
                    "account_id": acc["id"], "signal_id": sig["id"],
                    "ticket": res.order, "pair": our_pair, "side": sig["side"],
                    "volume": volume, "sl": sig["sl"], "tp": sig["tp"],
                    "status": "open",
                })
                print(f"      -> ticket {res.order}")
            mt5.shutdown()

    # 5) admin close commands
    try:
        cmds = sb_select("commands?status=eq.pending&order=created_at.asc"
                         "&select=id,account_id,action,ticket")
    except Exception:
        cmds = []
    for cmd in cmds:
        targets = [cmd["account_id"]] if cmd["account_id"] else [a["id"] for a in accounts]
        for acc_id in targets:
            cred = cred_by_acc.get(acc_id)
            if not cred:
                continue
            symbol_map = mt5_account(SYMBOL_MAP, cred)
            if symbol_map is None:
                continue
            if cmd["action"] == "close_all":
                open_pos = mt5.positions_get()
                open_pos = [p for p in open_pos if p.magic == MAGIC] if open_pos else []
                for p in open_pos:
                    r = close_position(p.ticket)
                    print(f"   [close_all] {acc_id} ticket {p.ticket}: {r}")
            elif cmd["action"] == "close_position" and cmd["ticket"]:
                r = close_position(cmd["ticket"])
                print(f"   [close] ticket {cmd['ticket']}: {r}")
            mt5.shutdown()
        sb_update(f"commands?id=eq.{cmd['id']}", {"status": "done"})

    # 6) reconcile: mark positions closed when they vanish from MT5
    try:
        open_pos = sb_select("positions?status=eq.open&select=id,account_id,ticket,pair,side,volume")
    except Exception:
        open_pos = []
    for p in open_pos:
        cred = cred_by_acc.get(p["account_id"])
        if not cred:
            continue
        symbol_map = mt5_account(SYMBOL_MAP, cred)
        if symbol_map is None:
            continue
        live = mt5.positions_get(ticket=p["ticket"]) if p["ticket"] else []
        if not live:
            # position gone -> closed. Infer win/loss from the signal's outcome.
            outcome = None
            if p["signal_id"]:
                try:
                    srow = sb_select(f"signals?id=eq.{p['signal_id']}&select=status")
                    if srow:
                        st = srow[0]["status"]
                        outcome = "closed_win" if st == "hit_tp" else ("closed_loss" if st == "hit_sl" else "closed_manual")
                except Exception:
                    pass
            outcome = outcome or "closed_manual"
            sb_update(f"positions?id=eq.{p['id']}", {"status": outcome, "closed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            print(f"   [reconcile] position {p['ticket']} -> {outcome}")
        else:
            # still open: refresh profit info (optional)
            pos = live[0]
            sb_update(f"positions?id=eq.{p['id']}", {"open_price": pos.price_open})
        mt5.shutdown()

    # advance watermark
    if sigs:
        watermark = max(watermark, dt.datetime.fromisoformat(sigs[-1]["created_at"].replace("Z", "+00:00")))
    return watermark


def main():
    global IGNORE_HOURS
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--ignore-hours", action="store_true",
                    help="place orders even outside trading hours (for testing)")
    args = ap.parse_args()
    IGNORE_HOURS = args.ignore_hours
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.")
        sys.exit(1)
    if not MT5_AVAILABLE:
        print("MetaTrader5 package missing: pip install MetaTrader5")
        sys.exit(1)
    # start watermark at now-2h so we don't replay ancient signals
    watermark = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    print("Octane Traders copier started.")
    while True:
        try:
            watermark = run_once(watermark)
        except Exception as e:
            print(f"   [error] {e}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
