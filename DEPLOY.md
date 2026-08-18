# Deploy: Scanner → Supabase → Netlify Dashboard

```
┌──────────────────────┐   POST (service-role key)   ┌──────────────┐   SELECT + Realtime (anon key)   ┌───────────────┐
│  GitHub repo +       │ ───────────────────────────▶ │   Supabase   │ ───────────────────────────────▶ │  Netlify site │
│  Actions (scanner.py)│                              │  (Postgres)  │                                   │  (dashboard/) │
│  runs on a schedule  │                              └──────────────┘                                   └───────────────┘
└──────────────────────┘
```

The scanner runs on **GitHub Actions** on a schedule (free), so nothing needs to
stay running on your computer.

## 1. Supabase (one-time setup, ~2 min)

1. Create a free project at [supabase.com](https://supabase.com).
2. Open **SQL Editor → New query**, paste the whole contents of
   [`supabase/schema.sql`](supabase/schema.sql), and **Run**.
   - This creates the `signals` table, indexes, RLS (public read), and
     enables realtime.
3. Grab your keys from **Project Settings → API**:
   - **Project URL** → e.g. `https://abcdxyz.supabase.co`
   - **`service_role` key** → used by the *scanner* to insert rows
     (secret — never put this in the dashboard/browser).
   - **`anon` key** → used by the *dashboard* to read rows (safe to expose).

## 2. GitHub repo + Actions (runs the scanner for you — no computer needed)

### 2a. Create the repo

1. Go to [github.com](https://github.com) → **New repository**
   - Name it e.g. `smc-signal-scanner`
   - Visibility: **public** = unlimited free Action minutes; private = 2,000
     min/month (fine at the default 30-min cadence)
   - Don't tick "Add a README" yet (empty repo is easier)

2. Upload these files/folders **exactly as they are** in the workspace:

```
smc-signal-scanner/            ← repo root
├── scanner.py                 ← the engine
├── requirements.txt           ← (empty — stdlib only)
├── .gitignore
├── .github/
│   └── workflows/
│       └── scan.yml           ← the schedule
├── supabase/
│   └── schema.sql             ← (already ran this in Step 1)
└── dashboard/                 ← (for Netlify in Step 3)
    ├── index.html
    ├── styles.css
    ├── app.js
    └── netlify.toml
```

   Easiest upload (no git CLI): on the repo page click **"uploading an existing
   file"** and drag the `scanner.py`, `requirements.txt`, `.gitignore`, plus the
   `supabase/` and `dashboard/` folders. For the hidden `.github/` folder use
   **Add file → Create new file**, type the path `.github/workflows/scan.yml`,
   paste the workflow's contents, and commit.

   *(Or use git CLI: `git init && git add . && git commit -m init && git remote
   add origin <url> && git push -u origin main`.)*

### 2b. Add your secrets (this is what connects the repo to Supabase)

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
2. Add **two** secrets:

| Secret name | Value |
|---|---|
| `SUPABASE_URL` | `https://xyz.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | the **service_role** key (Step 1) |

### 2c. Turn it on

1. Go to the **Actions** tab → click the `SMC Scan` workflow → **Enable workflow**
   (GitHub disables scheduled workflows on forked/new repos until you enable it)
2. Click **Run workflow** → **Run workflow** (manual test run)
3. Watch the run — you should see the scan output, and signals should appear in
   your dashboard. If it prints `[supabase: ok]` per signal, you're live.

It now runs automatically every 30 minutes (edit the `cron:` in
`.github/workflows/scan.yml` to change frequency or restrict to market hours —
examples are in the file).

> **Local option (optional):** you can still run it on your own machine if you
> prefer, with `export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...` then
> `python3 scanner.py`. The Actions route is just the hands-off version.

Every qualifying setup (score ≥ `--min-score`) is POSTed to the `signals`
table. Duplicates are rejected automatically (unique `signal_key`), so
overlapping/overlapping runs are safe.

## 3. Dashboard on Netlify

**Option A — drag & drop (fastest):**
1. Log in to [app.netlify.com](https://app.netlify.com).
2. Drag the **`dashboard/`** folder onto the "Deploys" tab.
3. Done — you get a URL like `https://something.netlify.app`.

**Option B — Git (recommended, since the repo already exists):**
1. The repo from Step 2 is already on GitHub.
2. In Netlify: **Add new site → Import from Git → GitHub** → pick the repo.
3. Set **Base directory** to `dashboard` (publish dir `.` is already in
   `netlify.toml`), then deploy.

**Connect the site to Supabase:**
- Open your Netlify URL and click **"Connect Supabase"**.
- Paste the **Project URL** and the **`anon` key**.
- Stored in your browser's localStorage only.

The dashboard loads the last 300 signals and **updates live** as the scanner
posts new ones (Supabase Realtime).

## 4. Daily workflow

1. GitHub Actions runs the scanner automatically every 30 min — do nothing.
2. Dashboard (phone or desktop) shows ★ setups as they appear, live.
3. Mark outcomes (hit TP / SL / expired) in the Supabase table editor
   (`status` column) to build a win-rate over time.

## Security notes

- The **service-role key bypasses RLS** — it lives only as a GitHub Actions
  secret and is injected at runtime. Never put it in code or the browser.
- The **anon key** can only `SELECT` (see the RLS policy in `schema.sql`) —
  that's why it's safe to ship in the browser.
- The dashboard is fully static: no Netlify Functions required.
- The scanner uses only the stdlib, so the Actions job has no supply-chain
  dependencies from PyPI.

## Where files live

| Path | What |
|---|---|
| `scanner.py` | SMC engine + Supabase push |
| `.github/workflows/scan.yml` | Scheduled Actions run |
| `requirements.txt` | (stdlib only — nothing to install) |
| `.gitignore` | Keeps secrets out of git |
| `supabase/schema.sql` | Table, indexes, RLS, realtime, stats view |
| `dashboard/index.html` | Dashboard UI |
| `dashboard/styles.css` | Styling |
| `dashboard/app.js` | Data loading (Supabase + demo mode) |
| `dashboard/netlify.toml` | Netlify static-site config |
