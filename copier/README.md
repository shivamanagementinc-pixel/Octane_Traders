# Octane Traders — Trade Copier (Stage 1)

Copies signals from Supabase into **multiple MT5 accounts**, sizing each trade
from that account's own risk % (default 0.5%), rounded **down** to the 0.01 lot
step.

## Two ways to run it

### 🪟 A) Standalone Windows .exe (no Python needed — recommended)

GitHub builds the exe for you — nothing to install on your PC:

1. In your repo: **Actions → "Build Copier (Windows .exe)" → Run workflow**
2. When it finishes, open the run → **Artifacts → `octane-copier-windows`** → download + unzip
3. You get:
   - `octane-copier.exe` — the copier (double-click to run)
   - `copier.ini.example` → rename to `copier.ini`, fill in your Supabase URL + service-role key
   - `config_local.py.example` → rename to `config_local.py` to override broker symbol names / pip values (optional)
4. Double-click `octane-copier.exe`. A console window opens and runs forever.

> ⚠️ **Requirements that never go away:** MT5 must be installed + running + logged
> in, with **Tools → Options → Expert Advisors → "Allow algorithmic trading"** ticked.
> The copier talks to the *running terminal*; if MT5 is closed, it can't trade.

### 🐍 B) From source (Python)

```bash
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
python3 copier.py --once      # test
python3 copier.py             # run forever
```

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

## Order mode: pending vs market

By default (`ORDER_MODE = "pending"`) the copier places a **LIMIT order at the
signal's entry price**, valid for `PENDING_TTL_MIN` (30) minutes. This avoids
"chasing" a price that drifted during the scan/copy lag:

- price retraces to entry → fills at a good price
- price runs away → the order expires and you skip (no bad chase)
- price already in your favour → fills immediately at the better market price

Set `ORDER_MODE = "market"` (or `order_mode = market` in `copier.ini`) for the
old immediate market-order behaviour.

## Safety defaults (Stage 1)

- Default risk = **0.5%** per trade per account (change per account in admin)
- Lot rounding = **down** to the 0.01 step (never exceeds the risk budget)
- Min lot 0.01, max 100, and MT5's own symbol min/step is also enforced
- Master kill-switch pauses new entries but still allows close commands
- Only signals with a valid stop distance are traded (no stop = skip)
- **Price sanity**: a signal whose price diverges >0.3% (FX) / >0.5% (gold,
  indices) from the broker's live quote is skipped (guards against futures-vs-
  spot and stale data)
- **Trading-hours guard**: new trades are only opened during London/NY
  (03:00–17:00 ET) and NOT during the 17:00–18:30 rollover blackout. Close
  commands and position reconciliation always run, 24/5.

## Run it 24/7 (systemd — auto-restart on reboot)

A ready-made service file is included (`octane-copier.service`):

```bash
sudo cp octane-copier.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now octane-copier
journalctl -u octane-copier -f     # tail logs
```

Edit the `WorkingDirectory`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
inside the .service file first.

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
