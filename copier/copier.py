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

VERSION = "2.4"  # bumped on each build; check the console banner to confirm the exe

# failed orders are not re-attempted within this many seconds (avoids 15s spam)
_order_failures = {}
RETRY_AFTER = 300

# Signals older than this are STALE and are never traded (market has moved on).
# The scanners close out signals within one 5-min cycle, so anything older than
# 10 minutes that is still "open" is either broken or already invalid.
MAX_SIGNAL_AGE_MIN = 10

# Signals open longer than this are marked "expired" (very likely broken — a
# legit signal in these short-term systems hits TP/SL well before an hour).
SWEEP_AGE_MIN = 60

# heartbeat throttle: when idle, only print the status line once per this long
_idle_heartbeat = 0.0
HEARTBEAT_SECS = 60

# Order placement mode:
#   "pending"  — place a LIMIT order at the signal's entry price, valid for
#                PENDING_TTL_MIN minutes (default). Avoids chasing a price that
#                drifted during the scan/copy lag: you either fill at a good
#                price or the order expires and you skip.
#   "market"   — place a market order immediately (old behaviour).
ORDER_MODE = "pending"
PENDING_TTL_MIN = 30

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


def filling_candidates(symbol):
    """Filling modes to try, in order. We do NOT trust the symbol's
    `filling_mode` bitmask (it's often 0 / misread by the package) — we simply
    try FOK -> IOC -> RETURN until one is accepted, which covers every broker.
    A config override FILLING_ORDER can reorder/limit this (e.g. "ioc,return").
    """
    override = _cfg("FILLING_ORDER")
    if override:
        order = []
        for tok in override.split(","):
            t = tok.strip().lower()
            if t in ("fok", "0"):
                order.append(mt5.ORDER_FILLING_FOK)
            elif t in ("ioc", "1"):
                order.append(mt5.ORDER_FILLING_IOC)
            elif t in ("return", "2"):
                order.append(mt5.ORDER_FILLING_RETURN)
        if order:
            return order
    return [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]


def _try_order(base):
    """Send an order, trying each filling mode until one works. Returns
    (result, None) on success or (None, last_result) on failure."""
    symbol = base["symbol"]
    last = None
    for filling in filling_candidates(symbol):
        req = dict(base)
        req["type_filling"] = filling
        result = mt5.order_send(req)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result, None
        name = {0: "FOK", 1: "IOC", 2: "RETURN"}.get(filling, str(filling))
        rc = result.retcode if result is not None else "?"
        print(f"      [filling] {name} -> retcode {rc} "
              f"({result.comment if result is not None else mt5.last_error()})")
        last = result
    return None, last


def _find_position(ticket_hint, symbol):
    """Find our open position after a deal. Some brokers return a deal ticket
    that differs from the position ticket, and positions can take a moment to
    appear — so retry, then fall back to matching by magic number + symbol."""
    for _ in range(8):                       # ~4s of retries
        if ticket_hint:
            pos = mt5.positions_get(ticket=ticket_hint)
            if pos:
                return pos[0]
        allpos = mt5.positions_get() or []
        cands = [p for p in allpos if p.magic == MAGIC and p.symbol == symbol]
        if cands:
            cands.sort(key=lambda p: p.time, reverse=True)
            return cands[0]
        time.sleep(0.5)
    return None


def _attach_sl_tp(ticket_hint, symbol, sl, tp):
    """Attach SL/TP to a freshly-opened position via TRADE_ACTION_SLTP.
    (MT5's Python package has NO `position_modify` — that was an MT4-ism.)
    Never raises: a failure returns False and the caller decides what to do."""
    try:
        pos = _find_position(ticket_hint, symbol)
        if pos is None:
            print(f"      [sltp] position not found (symbol {symbol})")
            return False
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": pos.ticket,
            "symbol": pos.symbol,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
        }
        res = mt5.order_send(req)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"      [sltp] SL/TP attached to ticket {pos.ticket}")
            return True
        print(f"      [sltp] attach failed: {res.comment if res is not None else mt5.last_error()}")
        return False
    except Exception as e:
        print(f"      [sltp] attach error: {e}")
        return False


def _valid_stops(side, sl, tp, price):
    try:
        sl = float(sl); tp = float(tp); price = float(price)
    except (TypeError, ValueError):
        return False, "bad numbers"
    if sl <= 0 or tp <= 0:
        return False, "zero stop"
    if side == "LONG":
        if not (sl < price < tp):
            return False, f"stops on wrong side (price {price}, sl {sl}, tp {tp})"
    else:
        if not (tp < price < sl):
            return False, f"stops on wrong side (price {price}, sl {sl}, tp {tp})"
    # generous sanity cap: stop further than 25% of price away is likely stale
    dist = abs(price - sl)
    if dist > abs(price) * 0.25:
        return False, f"stop too far ({dist:.5f} from price)"
    return True, ""


def price_sanity(pair, signal_price, live_price):
    """Refuse trades whose signal price is far from the broker's live price.

    The scanners use Yahoo data (gold FUTURES for XAUUSD, index futures for the
    CFDs). Those can diverge from the broker's spot/CFD quotes — gold futures
    vs spot has been off by $50+ in this market. If the divergence is beyond a
    small tolerance, the levels are meaningless on this account -> skip.

    Returns (ok, pct_deviation).
    """
    try:
        signal_price = float(signal_price)
        live_price = float(live_price)
    except (TypeError, ValueError):
        return False, None
    if live_price <= 0:
        return False, None
    pct = abs(signal_price - live_price) / live_price * 100.0
    if pair in ("XAUUSD", "XAGUSD"):
        tol = float(_cfg("PRICE_TOL_PCT_METALS") or 0.5)
    elif pair in ("SPX500", "NAS100", "US30"):
        tol = float(_cfg("PRICE_TOL_PCT_INDEX") or 0.5)
    else:
        tol = float(_cfg("PRICE_TOL_PCT_FX") or 0.3)
    return pct <= tol, round(pct, 2)


def place_order(actual_sym, side, volume, sl, tp, comment):
    symbol = actual_sym
    price = mt5.symbol_info_tick(symbol)
    if price is None:
        print(f"   [!] no tick for {symbol}")
        return None
    cur = price.bid if side == "SHORT" else price.ask
    ok_stops, why = _valid_stops(side, sl, tp, cur)
    if not ok_stops:
        print(f"   [skip] invalid stops for {symbol}: {why}")
        return None
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if side == "LONG" else mt5.ORDER_TYPE_SELL,
        "price": cur,
        "sl": float(sl),
        "tp": float(tp),
        "magic": MAGIC,
        "comment": comment[:27],
        "type_time": mt5.ORDER_TIME_GTC,
        "deviation": 20,
    }
    result, last = _try_order(base)
    if result is not None:
        return result

    # Fallback: bare market order, then attach SL/TP. SAFETY: if the attach
    # fails, close the bare position immediately — never hold it naked.
    bare = dict(base)
    bare.pop("sl", None)
    bare.pop("tp", None)
    bare["type_filling"] = mt5.ORDER_FILLING_IOC
    result2 = mt5.order_send(bare)
    if result2 is not None and result2.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"      [filling] placed bare IOC order, attaching SL/TP...")
        attached = _attach_sl_tp(getattr(result2, "order", None), symbol, sl, tp)
        if not attached:
            print(f"      [safety] SL/TP attach FAILED — closing bare position")
            _try_close_any(symbol)
        return result2

    print(f"   [!] order failed {symbol}: "
          f"{last.comment if last is not None else mt5.last_error()}")
    return None


def place_pending_order(actual_sym, side, entry_price, volume, sl, tp, comment):
    """Place a LIMIT order at the signal's entry price, valid for
    PENDING_TTL_MIN minutes, with SL/TP attached (or attach after fill if the
    broker rejects stops on the pending order). Returns a dict with
    {'ok': True, 'order': ticket, 'needs_sltp_after_fill': bool} or
    {'ok': False, 'reason': str}."""
    symbol = actual_sym
    try:
        entry_price = float(entry_price)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "bad entry price"}

    try:
        ttl_min = float(_cfg("PENDING_TTL_MIN") or PENDING_TTL_MIN)
    except (TypeError, ValueError):
        ttl_min = PENDING_TTL_MIN
    exp = int(time.time() + ttl_min * 60)
    base = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY_LIMIT if side == "LONG" else mt5.ORDER_TYPE_SELL_LIMIT,
        "price": entry_price,
        "sl": float(sl),
        "tp": float(tp),
        "magic": MAGIC,
        "comment": comment[:27],
        "type_time": mt5.ORDER_TIME_SPECIFIED,
        "type_filling": mt5.ORDER_FILLING_RETURN,
        "expiration": exp,
    }

    # try WITH SL/TP + expiration first
    result = mt5.order_send(dict(base))
    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "order": result.order, "needs_sltp_after_fill": False}

    # some brokers reject `expiration` ("Invalid expiration" = retcode 10023)
    # -> retry as a GTC limit (no expiry) and enforce the 30-min window
    # ourselves in the copier's reconcile step.
    rc = result.retcode if result is not None else -1
    if rc == 10023:
        base.pop("expiration", None)
        base["type_time"] = mt5.ORDER_TIME_GTC
        result = mt5.order_send(dict(base))
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            print("      [pending] broker rejected expiration -> placed GTC limit "
                  "(copier enforces the 30-min window)")
            return {"ok": True, "order": result.order, "needs_sltp_after_fill": False}

    # fallback: bare limit order (attach SL/TP after it fills); also drop the
    # expiration since this broker path already implies a picky symbol.
    bare = dict(base)
    bare.pop("sl", None)
    bare.pop("tp", None)
    bare.pop("expiration", None)
    bare["type_time"] = mt5.ORDER_TIME_GTC
    result2 = mt5.order_send(bare)
    if result2 is not None and result2.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"      [pending] limit placed WITHOUT SL/TP (will attach on fill)")
        return {"ok": True, "order": result2.order, "needs_sltp_after_fill": True}

    msg = result2.comment if result2 is not None else (result.comment if result is not None else mt5.last_error())
    return {"ok": False, "reason": msg}


def _existing_pending(symbol):
    """Any of OUR pending orders already open on this symbol? -> ticket or None."""
    try:
        orders = mt5.orders_get(symbol=symbol) or []
    except Exception:
        return None
    for o in orders:
        if o.magic == MAGIC:
            return o.ticket
    return None


def _try_close_any(symbol):
    """Close every open position on `symbol` bearing our magic number."""
    allpos = mt5.positions_get() or []
    for p in allpos:
        if p.magic == MAGIC and p.symbol == symbol:
            close_position(p.ticket)


def close_position(ticket):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return "already_closed"
    pos = pos[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return "no_tick"
    base = {"action": mt5.TRADE_ACTION_DEAL, "position": pos.ticket,
            "symbol": pos.symbol, "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask,
            "magic": MAGIC, "comment": "octane-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "deviation": 20}
    result, last = _try_order(base)
    if result is not None:
        return "closed"
    return f"failed: {last.comment if last is not None else mt5.last_error()}"


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
                         "&select=id,pair,side,sl,tp,pips_sl,strategy,created_at,price")
    except Exception as e:
        print(f"   [!] signals read failed: {e}")
        sigs = []

    # 3b) split into FRESH (tradeable) vs STALE (skip + mark expired)
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    fresh_sigs, stale_sigs = [], []
    for s in sigs:
        try:
            age_min = (now_ts - dt.datetime.fromisoformat(
                str(s["created_at"]).replace("Z", "+00:00")).timestamp()) / 60.0
        except Exception:
            age_min = 999
        (fresh_sigs if age_min <= MAX_SIGNAL_AGE_MIN else stale_sigs).append((s, age_min))

    # 3c) sweep: signals older than SWEEP_AGE_MIN are almost certainly broken
    #     (or the scanners' close-out missed them) -> mark "expired" so they
    #     stop cluttering the dashboard and are never re-attempted.
    #     Signals between MAX_SIGNAL_AGE_MIN and SWEEP_AGE_MIN are skipped
    #     (not traded) but left open — the scanner may still close them.
    for s, age_min in stale_sigs:
        if age_min >= SWEEP_AGE_MIN:
            try:
                sb_update(f"signals?id=eq.{s['id']}", {"status": "expired"})
                print(f"   [sweep] stale {s['pair']} {s['side']} ({int(age_min)}m old) -> expired")
            except Exception as e:
                print(f"   [sweep] failed {s['id']}: {e}")
        else:
            print(f"   [stale] skipping {s['pair']} {s['side']} ({int(age_min)}m old — not traded)")
    sigs = [s for s, _ in fresh_sigs]

    # 4) already-placed signal ids per account (avoid double-entry)
    try:
        placed = sb_select("positions?status=eq.open&select=account_id,signal_id")
        placed_keys = {(p["account_id"], p["signal_id"]) for p in placed if p["signal_id"]}
    except Exception:
        placed_keys = set()

    global _idle_heartbeat
    show = bool(sigs) or (time.time() - _idle_heartbeat >= HEARTBEAT_SECS)
    if show:
        print(f"   [copier] {len(accounts)} account(s) connected, {len(sigs)} new signal(s)")
        if not enabled:
            print(f"   [kill-switch] trading paused — processing only admin close commands")
        elif not (trading_allowed() or test_mode or IGNORE_HOURS):
            print(f"   [hours] outside trading session/blackout — not opening new trades")
        elif test_mode:
            print(f"   [test-mode] hours guard bypassed — will place demo orders")
        if not sigs:
            _idle_heartbeat = time.time()

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
            # price sanity: is the signal's price close to THIS broker's live
            # price? (data-source mismatch guard — futures vs spot, stale data)
            tick = mt5.symbol_info_tick(sym) if MT5_AVAILABLE else None
            live_price = tick.bid if tick is not None else None
            ok_price, pct = price_sanity(our_pair, sig.get("price"), live_price)
            if not ok_price:
                print(f"   [skip] {our_pair} price mismatch: signal "
                      f"{sig.get('price')} vs broker {live_price} ({pct}% off)")
                _order_failures[(acc["id"], sig["id"])] = time.time()
                mt5.shutdown()
                continue
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
            # skip signals that failed recently (avoid retry spam every 15s)
            fail_key = (acc["id"], sig["id"])
            if time.time() - _order_failures.get(fail_key, 0) < RETRY_AFTER:
                mt5.shutdown()
                continue
            # dedup: never stack a second order if we already hold a pending
            # order (or open position) on this symbol.
            if _existing_pending(sym):
                print(f"      [dup] pending order already open for {sym} — skipping")
                _order_failures[fail_key] = time.time()
                mt5.shutdown()
                continue

            mode = _cfg("ORDER_MODE") or ORDER_MODE
            entry_price = sig.get("price")
            if mode == "pending" and entry_price:
                out = place_pending_order(sym, sig["side"], entry_price, volume,
                                          sig["sl"], sig["tp"],
                                          f"octane {our_pair} {sig['side']}")
                if not out.get("ok"):
                    _order_failures[fail_key] = time.time()
                    print(f"   [pending] failed {sym}: {out.get('reason')}")
                    mt5.shutdown()
                    continue
                sb_insert("positions", {
                    "account_id": acc["id"], "signal_id": sig["id"],
                    "ticket": out["order"], "pair": our_pair, "side": sig["side"],
                    "volume": volume, "sl": sig["sl"], "tp": sig["tp"],
                    "status": "pending",
                })
                print(f"      -> pending LIMIT @ {entry_price:.5f} "
                      f"(order {out['order']}, expires in {PENDING_TTL_MIN} min)")
            else:
                res = place_order(sym, sig["side"], volume, sig["sl"], sig["tp"],
                                  f"octane {our_pair} {sig['side']}")
                if res is None:
                    _order_failures[fail_key] = time.time()
                    mt5.shutdown()
                    continue
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
                # cancel pending orders AND close open positions
                for o in (mt5.orders_get() or []):
                    if o.magic == MAGIC:
                        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
                        print(f"   [close_all] cancelled pending {o.ticket}")
                open_pos = mt5.positions_get()
                open_pos = [p for p in open_pos if p.magic == MAGIC] if open_pos else []
                for p in open_pos:
                    r = close_position(p.ticket)
                    print(f"   [close_all] {acc_id} ticket {p.ticket}: {r}")
            elif cmd["action"] == "close_position" and cmd["ticket"]:
                r = close_position(cmd["ticket"])
                print(f"   [close] ticket {cmd['ticket']}: {r}")
            elif cmd["action"] == "cancel_pending" and cmd["ticket"]:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": cmd["ticket"]})
                ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
                print(f"   [cancel] pending {cmd['ticket']}: "
                      f"{'cancelled' if ok else (res.comment if res else mt5.last_error())}")
            mt5.shutdown()
        sb_update(f"commands?id=eq.{cmd['id']}", {"status": "done"})

    # 6) reconcile: mark positions closed when they vanish from MT5
    try:
        open_pos = sb_select("positions?status=eq.open&select=id,account_id,ticket,pair,side,volume,signal_id,sl,tp")
        pend_pos = sb_select("positions?status=eq.pending&select=id,account_id,ticket,pair,side,volume,signal_id,sl,tp")
    except Exception:
        open_pos, pend_pos = [], []

    # 6a) pending orders: did they fill (-> position), expire (broker TTL), or
    #     outlive our window (GTC fallback -> we cancel them ourselves)?
    try:
        ttl_min = float(_cfg("PENDING_TTL_MIN") or PENDING_TTL_MIN)
    except (TypeError, ValueError):
        ttl_min = PENDING_TTL_MIN
    for p in pend_pos:
        cred = cred_by_acc.get(p["account_id"])
        if not cred:
            continue
        symbol_map = mt5_account(SYMBOL_MAP, cred)
        if symbol_map is None:
            continue
        order = mt5.orders_get(ticket=p["ticket"]) if p["ticket"] else []
        if order:
            # still pending. If it's a GTC order (no broker expiry) that has
            # outlived our window, cancel it ourselves.
            try:
                opened = dt.datetime.fromisoformat(str(p["opened_at"]).replace("Z", "+00:00"))
                age_min = (dt.datetime.now(dt.timezone.utc) - opened).total_seconds() / 60.0
            except Exception:
                age_min = 0
            if age_min > ttl_min:
                r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": p["ticket"]})
                ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
                sb_update(f"positions?id=eq.{p['id']}",
                          {"status": "expired",
                           "closed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
                print(f"   [reconcile] pending {p['pair']} expired by copier "
                      f"({int(age_min)}m > {int(ttl_min)}m) "
                      f"{'— cancelled' if ok else '— cancel failed'}")
            mt5.shutdown()
            continue
        # order is gone: either filled or expired
        actual_sym = symbol_map.get(p["pair"])
        allpos = mt5.positions_get() or []
        filled = [x for x in allpos
                  if x.magic == MAGIC and (actual_sym is None or x.symbol == actual_sym)]
        if filled:
            pos = filled[0]
            # ensure SL/TP (in case the limit was placed bare)
            _attach_sl_tp(pos.ticket, actual_sym or pos.symbol, p["sl"], p["tp"])
            sb_update(f"positions?id=eq.{p['id']}",
                      {"status": "open", "ticket": pos.ticket})
            print(f"   [reconcile] pending {p['pair']} FILLED -> ticket {pos.ticket}")
        else:
            sb_update(f"positions?id=eq.{p['id']}",
                      {"status": "expired",
                       "closed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            print(f"   [reconcile] pending {p['pair']} expired (never triggered)")
        mt5.shutdown()

    # 6b) open positions: mark closed when they vanish from MT5
    for p in open_pos:
        cred = cred_by_acc.get(p["account_id"])
        if not cred:
            continue
        symbol_map = mt5_account(SYMBOL_MAP, cred)
        if symbol_map is None:
            continue
        live = mt5.positions_get(ticket=p["ticket"]) if p["ticket"] else []
        if not live:
            # fallback: match by magic + symbol (ticket may differ from ours)
            actual_sym = symbol_map.get(p["pair"])
            allpos = mt5.positions_get() or []
            live = [x for x in allpos
                    if x.magic == MAGIC and (actual_sym is None or x.symbol == actual_sym)]
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
    print(f"Octane Traders copier v{VERSION} started.")
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
