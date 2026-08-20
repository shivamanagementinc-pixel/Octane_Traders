"""Octane Traders — copier configuration.

Broker-specific values live here. Adjust for YOUR broker before going live.

- USD_PER_UNIT_LOT : how many USD one "signal unit" move is worth per 1.0 lot.
    signal unit = pip (FX pairs), $1 (XAUUSD), point (indices)
- SYMBOL_MAP       : our pair name -> your MT5 symbol name (brokers vary!)
- SYMBOL_SUFFIX    : per-account suffix override (e.g. "EURUSD.a" -> suffix ".a")
"""

# USD value of one signal-unit move per 1.0 lot, per symbol (typical USD-account
# values — VERIFY against your broker's contract specs).
USD_PER_UNIT_LOT = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "AUDUSD": 10.0,
    "NZDUSD": 10.0,
    "USDCHF": 10.5,
    "USDJPY": 6.5,
    "USDCAD": 7.2,
    "XAUUSD": 100.0,   # gold: $1 move per lot = $100 (100 oz contract)
    "XAGUSD": 50.0,
    "SPX500": 1.0,     # indices: 1 point per contract
    "NAS100": 1.0,
    "US30":   1.0,
}

# Our internal pair name -> MT5 symbol (your broker: FX plain, CFDs use .c).
SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "USDCAD": "USDCAD",
    "USDCHF": "USDCHF",
    "USDJPY": "USDJPY",
    "XAUUSD": "XAUUSD",
    "XAGUSD": "XAGUSD",
    "SPX500": "SPCUSD.c",   # S&P 500
    "NAS100": "NACUSD.c",   # Nasdaq 100
    "US30":   "DJCUSD.c",   # Dow Jones 30
}

# Lot sizing rules (defaults; overridable per account in the admin dashboard).
DEFAULT_RISK_PCT = 0.5
MIN_LOT = 0.01
MAX_LOT = 100.0
LOT_STEP = 0.01

# Magic number stamped on every order so the copier can recognise its own trades.
MAGIC = 20260819
