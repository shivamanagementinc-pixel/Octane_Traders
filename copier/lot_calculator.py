#!/usr/bin/env python3
"""Octane Traders — risk-based lot sizing.

    lots = (balance * risk% / 100) / (stop_units * usd_per_unit_lot)

rounded DOWN to the symbol step (safer — never exceeds the risk budget),
floored at the minimum lot and capped at the maximum.

Pure functions — no MT5 needed, fully unit-testable.
"""

from decimal import Decimal, ROUND_DOWN

from config import USD_PER_UNIT_LOT, MIN_LOT, MAX_LOT, LOT_STEP, DEFAULT_RISK_PCT


def floor_to_step(lots, step=LOT_STEP):
    """Round DOWN to the nearest step (0.1354 -> 0.13), then clamp min/max."""
    q = Decimal(str(step))
    d = Decimal(str(lots)).quantize(q, rounding=ROUND_DOWN)
    d = max(Decimal(str(MIN_LOT)), min(Decimal(str(MAX_LOT)), d))
    return float(d)


def size_lots(balance, risk_pct, stop_units, pair, unit_lookup=None):
    """Return the lot size for a trade, or 0.0 if it cannot be sized safely.

    balance     — account balance (float)
    risk_pct    — % of balance to risk per trade (0.5 = 0.5%)
    stop_units  — stop distance in the pair's unit (pips / $ / points)
    pair        — e.g. "EURUSD"
    unit_lookup — optional dict override of USD-per-unit-per-lot (used by the
                  copier so config_local.py overrides reach sizing)
    """
    if stop_units is None or stop_units <= 0:
        return 0.0                      # can't size without a stop -> skip
    if balance is None or balance <= 0:
        return 0.0
    if risk_pct is None or risk_pct <= 0:
        risk_pct = DEFAULT_RISK_PCT
    lookup = unit_lookup if unit_lookup is not None else USD_PER_UNIT_LOT
    unit_value = lookup.get(pair)
    if not unit_value:
        return 0.0                      # unknown symbol -> don't guess
    risk_usd = float(balance) * (float(risk_pct) / 100.0)
    raw_lots = risk_usd / (float(stop_units) * unit_value)
    return floor_to_step(raw_lots)


if __name__ == "__main__":
    # quick self-test
    cases = [
        (10000, 0.5, 20.0, "EURUSD"),   # 50 / (20*10) = 0.25
        (10000, 0.5, 37.0, "EURUSD"),   # 50 / 370 = 0.1351 -> 0.13 (floor)
        (10000, 1.0, 8.0,  "USDJPY"),   # 100 / (8*6.5) = 1.923 -> 1.92
        (100,   0.5, 20.0, "EURUSD"),   # 0.5 / 200 = 0.0025 -> 0.01 (min)
        (100000, 2.0, 3.0, "EURUSD"),   # 2000 / 30 = 66.66 -> 66.66
        (5000,  0.5, 0.0,  "EURUSD"),   # no stop -> 0.0 (skip)
    ]
    for bal, rp, st, pair in cases:
        print(f"balance={bal:>7} risk={rp}% stop={st:<5} {pair:<7} -> "
              f"{size_lots(bal, rp, st, pair):.2f} lots")
