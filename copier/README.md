# Octane Traders — Trade Copier (Stage 1)

Copies signals from Supabase into **multiple MT5 accounts**, sizing each trade
from that account's own risk % (default 0.5%), rounded **down** to the 0.01 lot
step.

## How it works

```
signals (Supabase) ──▶ copier.py ──▶ each active MT5 account
                        │
                        ├─ sizes lots per account: risk% × balance ÷ (stop × pip-value)
                        ├─ places market orders with SL/TP (magic number = ours)
                        ├─ writes positions back to Supabase
                        ├─ processes admin close commands + kill-switch
                        └─ reconciles closed positions (win/loss)
```

## Setup on your VPS

1. **Install MT5** on the VPS (Windows VPS, or Linux VPS + Wine). Log in once
   per account so the terminal is authorised. *(The `MetaTrader5` Python package
   requires a running MT5 terminal installed on the same machine.)*

2. **Install Python deps:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Export your Supabase service-role credentials:**
   ```bash
   export SUPABASE_URL=https://YOUR-REF.supabase.co
   export SUPABASE_SERVICE_ROLE_KEY=sb_secret_...
   ```

4. **Add your accounts** in the admin dashboard
   (`https://your-site.netlify.app/admin.html`) → "+ Add account" → enter the
   MT5 login / password / server / risk %. Credentials are stored insert-only
   (the browser can never read them back; only the copier's service-role key can).

5. **Adjust broker-specific values** in `config.py`:
   - `SYMBOL_MAP` — your broker's index symbol names (e.g. `US500` vs `SPX500`)
   - `USD_PER_UNIT_LOT` — pip value per 1.0 lot (VERIFY against your broker)
   - `SYMBOL_SUFFIX` per account — e.g. `.a` for some brokers

6. **Run it:**
   ```bash
   python3 copier.py --once      # single test pass — check the log
   python3 copier.py             # run forever (use tmux / systemd / pm2)
   ```

## Safety defaults (Stage 1)

- Default risk = **0.5%** per trade per account (change per account in admin)
- Lot rounding = **down** to the 0.01 step (never exceeds the risk budget)
- Min lot 0.01, max 100, and MT5's own symbol min/step is also enforced
- Master kill-switch pauses new entries but still allows close commands
- Only signals with a valid stop distance are traded (no stop = skip)

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MetaTrader5 package missing` | `pip install MetaTrader5` |
| `init failed` | Wrong login/password/server, or MT5 terminal not running on the VPS |
| `symbol X not available` | Wrong symbol name for your broker — fix `SYMBOL_MAP` / suffix |
| `order failed ... FOK` | Filling mode; some brokers need `ORDER_FILLING_IOC` or `RETURN` |
| No trades placed | Check kill-switch is ON, account `active` is ON, and `risk_pct` > 0 |

## Stage 2 (live subscriber accounts) — plan

- Add Supabase Auth + an Edge Function so admin operations require login
- Move credentials fully server-side (never stored via browser)
- Per-subscriber accounts + a billing/entitlement check
- Swap the MT5 gateway to MetaApi (cloud) for scale — the sizing/reporting
  logic in this copier ports over unchanged.
