/* SMC Signal Dashboard — signals + performance report + outcome marking. */

const LS_URL = "smc.supa.url";
const LS_KEY = "smc.supa.key";

/* ------------------------------------------------------------------ utils */
const $ = (id) => document.getElementById(id);

function fmtPrice(pair, v) {
  if (v == null) return "—";
  if (pair === "XAUUSD") return Number(v).toFixed(2);
  if (pair.endsWith("JPY")) return Number(v).toFixed(3);
  return Number(v).toFixed(5);
}
function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
const scoreClass = (s) => (s >= 80 ? "score-hi" : s >= 70 ? "score-mid" : "score-lo");
const statusClass = (st) => ({ hit_tp: "st-win", hit_sl: "st-loss", expired: "st-exp" }[st] || "st-open");
const R = (v) => (v > 0 ? "+" : "") + v.toFixed(2) + "R";

/* -------------------------------------------------------- backtest dataset */
/* Historical trades from the walk-forward backtests (see backtest-data.js and
   scalp-backtest-data.js). Merged into the signal history so everything lives
   on one page, tagged by strategy. */
function backtestSignals() {
  const arr = (window.BACKTEST_TRADES || []).slice().sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at));
  return arr.map((t, i) => ({ ...t, id: "bt-" + i, source: "backtest", is_backtest: true, strategy: "smc" }));
}
function scalpBacktestSignals() {
  const arr = (window.SCALP_BACKTEST_TRADES || []).slice().sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at));
  return arr.map((t, i) => ({ ...t, id: "sc-" + i, source: "backtest", is_backtest: true, strategy: "scalp" }));
}
const showBacktest = () => $("filter-backtest").checked;
const strat = (s) => s.strategy || "smc";

/* --------------------------------------------------------------- demo data */
function demoSignals() {
  const now = Date.now();
  let i = 0;
  const mk = (o, minsAgo) => ({ id: "d" + (++i), created_at: new Date(now - minsAgo * 60000).toISOString(), status: "open", ...o });
  return [
    mk({ pair: "GBPJPY", side: "LONG", score: 93, price: 216.005, zone_lo: 215.999, zone_hi: 216.004, zone_type: "FVG", sl: 215.950, tp: 216.216, pips_tp: 21.1, pips_sl: 5.5, rr: 3.87, htf_bias: "bull", deal_pos: 48.6, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block", "inside FVG", "R:R 3.87"] }, 4),
    mk({ pair: "EURUSD", side: "LONG", score: 85, price: 1.15821, zone_lo: 1.15808, zone_hi: 1.15821, zone_type: "FVG", sl: 1.15758, tp: 1.16023, pips_tp: 20.2, pips_sl: 6.4, rr: 3.17, htf_bias: "bull", deal_pos: 100.0, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block", "inside FVG", "R:R 3.17"] }, 18),
    mk({ pair: "USDJPY", side: "LONG", score: 78, price: 159.694, zone_lo: 159.684, zone_hi: 159.710, zone_type: "OB", sl: 159.660, tp: 159.910, pips_tp: 21.6, pips_sl: 3.4, rr: 6.35, htf_bias: "bull", deal_pos: 62.0, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block"] }, 32),
    mk({ pair: "GBPUSD", side: "LONG", score: 73, price: 1.35316, zone_lo: 1.35305, zone_hi: 1.35336, zone_type: "OB", sl: 1.35264, tp: 1.35525, pips_tp: 20.9, pips_sl: 5.2, rr: 4.02, htf_bias: "flat", deal_pos: 80.5, reasons: ["sell-side liq swept + reclaim", "inside Order Block", "inside FVG"] }, 41),
    mk({ pair: "USDCAD", side: "LONG", score: 73, price: 1.38736, zone_lo: 1.38670, zone_hi: 1.38787, zone_type: "OB", sl: 1.38646, tp: 1.39211, pips_tp: 47.5, pips_sl: 9.0, rr: 5.27, htf_bias: "flat", deal_pos: 79.0, reasons: ["sell-side liq swept + reclaim", "inside Order Block", "R:R 5.27"] }, 55),
    mk({ pair: "XAUUSD", side: "SHORT", score: 73, price: 4447.90, zone_lo: 4446.90, zone_hi: 4450.00, zone_type: "FVG", sl: 4455.83, tp: 4427.50, pips_tp: 20.4, pips_sl: 7.9, rr: 2.58, htf_bias: "flat", deal_pos: 32.2, reasons: ["buy-side liq swept + reclaim", "inside Order Block", "inside FVG"] }, 70),
    // closed — for the performance report demo
    { id: "d" + (++i), pair: "AUDJPY", side: "LONG", score: 81, price: 113.542, zone_lo: 113.534, zone_hi: 113.553, zone_type: "FVG", sl: 113.500, tp: 113.760, pips_tp: 21.8, pips_sl: 4.2, rr: 5.19, htf_bias: "bull", deal_pos: 76.0, status: "hit_tp", reasons: ["HTF bullish", "sell-side liq swept + reclaim", "inside FVG"], created_at: new Date(now - 130 * 60000).toISOString() },
    { id: "d" + (++i), pair: "XAUUSD", side: "LONG", score: 75, price: 4440.0, zone_lo: 4438.0, zone_hi: 4442.0, zone_type: "OB", sl: 4430.0, tp: 4468.0, pips_tp: 28.0, pips_sl: 10.0, rr: 2.8, htf_bias: "bull", deal_pos: 40.0, status: "hit_tp", reasons: ["HTF bullish", "sell-side liq swept + reclaim", "inside Order Block"], created_at: new Date(now - 200 * 60000).toISOString() },
    { id: "d" + (++i), pair: "GBPUSD", side: "LONG", score: 79, price: 1.3510, zone_lo: 1.3508, zone_hi: 1.3512, zone_type: "FVG", sl: 1.3502, tp: 1.3530, pips_tp: 20.0, pips_sl: 8.0, rr: 2.5, htf_bias: "bull", deal_pos: 60.0, status: "hit_tp", reasons: ["HTF bullish", "inside FVG"], created_at: new Date(now - 300 * 60000).toISOString() },
    { id: "d" + (++i), pair: "EURJPY", side: "SHORT", score: 66, price: 184.856, zone_lo: 184.849, zone_hi: 184.880, zone_type: "OB", sl: 184.950, tp: 184.640, pips_tp: 21.6, pips_sl: 9.4, rr: 2.30, htf_bias: "bear", deal_pos: 45.0, status: "hit_sl", reasons: ["HTF bearish", "inside Order Block"], created_at: new Date(now - 400 * 60000).toISOString() },
    { id: "d" + (++i), pair: "USDJPY", side: "SHORT", score: 70, price: 159.60, zone_lo: 159.58, zone_hi: 159.64, zone_type: "OB", sl: 159.70, tp: 159.40, pips_tp: 20.0, pips_sl: 10.0, rr: 2.0, htf_bias: "bear", deal_pos: 55.0, status: "hit_sl", reasons: ["HTF bearish", "inside Order Block"], created_at: new Date(now - 500 * 60000).toISOString() },
  ];
}

/* ------------------------------------------------------------------ state */
const state = { signals: [], mode: "demo", client: null, channel: null, strategy: "smc" };

function getConfig() {
  const url = localStorage.getItem(LS_URL);
  const key = localStorage.getItem(LS_KEY);
  return url && key ? { url, key } : null;
}

/* ------------------------------------------------------------------ filters */
function filtered() {
  const pair = $("filter-pair").value;
  const side = $("filter-side").value;
  const minScore = Number($("filter-score").value || 0);
  const openOnly = $("filter-open").checked;
  const bt = showBacktest();
  return state.signals.filter((s) =>
    strat(s) === state.strategy &&
    (bt || s.source !== "backtest") &&
    (!pair || s.pair === pair) &&
    (!side || s.side === side) &&
    (state.strategy === "scalp" || s.score >= minScore) &&
    (!openOnly || s.status === "open")
  );
}

/* ------------------------------------------------------------- performance */
function computePerf(sigs) {
  const closed = sigs.filter((s) => s.status === "hit_tp" || s.status === "hit_sl");
  const wins = closed.filter((s) => s.status === "hit_tp");
  const losses = closed.filter((s) => s.status === "hit_sl");
  const n = closed.length;
  const winRate = n ? (wins.length / n) * 100 : 0;
  const totalR = closed.reduce((a, s) => a + (s.status === "hit_tp" ? Number(s.rr) : -1), 0);
  const expectancy = n ? totalR / n : 0;
  const grossWin = wins.reduce((a, s) => a + Number(s.rr), 0);
  const pf = losses.length ? grossWin / losses.length : (wins.length ? Infinity : 0);
  const avgScoreWin = wins.length ? wins.reduce((a, s) => a + s.score, 0) / wins.length : null;
  const avgScoreLoss = losses.length ? losses.reduce((a, s) => a + s.score, 0) / losses.length : null;

  const byPair = {};
  for (const s of closed) {
    const b = byPair[s.pair] || (byPair[s.pair] = { w: 0, l: 0, r: 0 });
    if (s.status === "hit_tp") { b.w += 1; b.r += Number(s.rr); } else { b.l += 1; b.r -= 1; }
  }
  const buckets = [["<70", 0, 70], ["70-79", 70, 80], ["80-89", 80, 90], ["90+", 90, 101]];
  const byScore = buckets.map(([label, lo, hi]) => {
    const c = closed.filter((s) => s.score >= lo && s.score < hi);
    const w = c.filter((s) => s.status === "hit_tp").length;
    const l = c.filter((s) => s.status === "hit_sl").length;
    return { label, w, l, wr: (w + l) ? (w / (w + l) * 100) : null };
  });

  return {
    closed: n, wins: wins.length, losses: losses.length, winRate,
    totalR, expectancy, pf, avgScoreWin, avgScoreLoss, byPair, byScore,
    expired: sigs.filter((s) => s.status === "expired").length,
    open: sigs.filter((s) => s.status === "open").length,
  };
}

function renderPerf() {
  const bt = showBacktest();
  const scope = state.signals.filter((s) => strat(s) === state.strategy && (bt || s.source !== "backtest"));
  const p = computePerf(scope);
  const pfTxt = p.pf === Infinity ? "∞" : p.pf.toFixed(2);
  $("perf-cards").innerHTML = [
    ["Win rate", (p.closed ? p.winRate.toFixed(0) + "%" : "—") + ` <small>${p.wins}W/${p.losses}L</small>`],
    ["Expectancy", p.closed ? R(p.expectancy) + " <small>per trade</small>" : "—"],
    ["Profit factor", p.closed ? pfTxt : "—"],
    ["Total P&L", p.closed ? R(p.totalR) + " <small>risk-units</small>" : "—"],
    ["Closed", p.closed + ` <small>${p.expired} expired · ${p.open} open</small>`],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  const scoreInsight = (p.avgScoreWin != null && p.avgScoreLoss != null)
    ? `<div class="note">Avg quality: <b>${p.avgScoreWin.toFixed(0)}</b> on winners vs <b>${p.avgScoreLoss.toFixed(0)}</b> on losers ${p.avgScoreWin > p.avgScoreLoss ? "→ score has edge ✅" : "→ score NOT predictive ⚠️"}</div>`
    : `<div class="note">Mark some outcomes (TP/SL) to unlock win-rate analytics.</div>`;

  $("perf-by-pair").innerHTML = `<h3>By pair</h3>` + scoreInsight +
    `<table class="mini"><thead><tr><th>Pair</th><th>W</th><th>L</th><th>Win%</th><th>Net R</th></tr></thead><tbody>` +
    Object.entries(p.byPair).sort((a, b) => (b[1].w + b[1].l) - (a[1].w + a[1].l))
      .map(([pair, b]) => {
        const wr = (b.w + b.l) ? ((b.w / (b.w + b.l)) * 100).toFixed(0) + "%" : "—";
        return `<tr><td class="pair-cell">${pair}</td><td class="num">${b.w}</td><td class="num">${b.l}</td><td class="num">${wr}</td><td class="num ${b.r >= 0 ? "c-win" : "c-loss"}">${R(b.r)}</td></tr>`;
      }).join("") + `</tbody></table>` || `<p class="empty">No closed trades yet.</p>`;

  $("perf-by-score").innerHTML = `<h3>By quality score</h3><div class="note">Does a higher score actually win more?${bt ? " (incl. backtest)" : " (live only)"}</div>` +
    `<table class="mini"><thead><tr><th>Score</th><th>W</th><th>L</th><th>Win%</th></tr></thead><tbody>` +
    p.byScore.map((b) => `<tr><td>${b.label}</td><td class="num">${b.w}</td><td class="num">${b.l}</td><td class="num">${b.wr == null ? "—" : b.wr.toFixed(0) + "%"}</td></tr>`).join("") +
    `</tbody></table>`;
}

/* ------------------------------------------------------------------ render */
function render() {
  const all = state.signals.filter((s) => strat(s) === state.strategy);
  const sigs = filtered();
  $("count").textContent = `${sigs.length} signal${sigs.length === 1 ? "" : "s"}`;
  // hide the quality-score filter on the scalp tab (scalps have no SMC score)
  const scoreFilter = $("filter-score").closest("label");
  if (scoreFilter) scoreFilter.style.display = state.strategy === "scalp" ? "none" : "";

  const open = all.filter((s) => s.status === "open").length;
  const hi = all.filter((s) => s.score >= 80).length;
  const wins = all.filter((s) => s.status === "hit_tp").length;
  const avg = all.length ? (all.reduce((a, s) => a + s.score, 0) / all.length).toFixed(1) : "—";
  const decided = all.filter((s) => s.status === "hit_tp" || s.status === "hit_sl").length;
  const wr = decided ? (wins / decided * 100).toFixed(0) + "%" : "—";
  const isScalp = state.strategy === "scalp";
  $("stats").innerHTML = isScalp ? [
    ["Signals", all.length],
    ["Open", open],
    ["Win rate", wr + `<small>${wins}W / ${decided - wins}L</small>`],
    ["Target", "1R" + `<small>1×ATR stop & target</small>`],
    ["Wins", wins],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")
  : [
    ["Signals", all.length],
    ["Open", open],
    ["★ ≥80", hi],
    ["Avg quality", avg],
    ["Wins", wins],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  const pairs = [...new Set(all.map((s) => s.pair))].sort();
  const cur = $("filter-pair").value;
  $("filter-pair").innerHTML = `<option value="">All</option>` +
    pairs.map((p) => `<option ${p === cur ? "selected" : ""}>${p}</option>`).join("");

  const stars = sigs.filter((s) => s.score >= 80 && s.status === "open");
  const featured = isScalp
    ? sigs.filter((s) => s.status === "open").slice(0, 6)
    : (stars.length ? stars.slice(0, 6) : sigs.filter((s) => s.status === "open").slice(0, 3));
  $("featured").innerHTML = featured.map((s) => `
    <div class="card ${!isScalp && s.score >= 80 ? "star" : ""}">
      <div class="top">
        <span class="pair">${s.pair} <span class="side-${s.side.toLowerCase()}">${s.side}</span></span>
        <span class="score-pill ${isScalp ? "score-hi" : scoreClass(s.score)}">${isScalp ? "1R" : s.score}</span>
      </div>
      <div class="levels">
        <div class="lv"><div class="k">Entry</div><div class="v">${fmtPrice(s.pair, s.price)}</div></div>
        <div class="lv"><div class="k">SL</div><div class="v">${fmtPrice(s.pair, s.sl)}</div></div>
        <div class="lv"><div class="k">TP</div><div class="v">${fmtPrice(s.pair, s.tp)}</div></div>
      </div>
      <div class="meta">
        +${s.pips_tp} ${s.pair === "XAUUSD" ? "$" : "pips"} target · R:R ${s.rr} · ${s.zone_type || ""} · ${fmtTime(s.created_at)}
      </div>
      ${s.reasons && s.reasons.length ? `<div class="why">${s.reasons.map((r) => `<span class="tag">${r}</span>`).join("")}</div>` : ""}
    </div>`).join("") || `<p class="empty">No featured setups right now.</p>`;

  const tbody = document.querySelector("#table tbody");
  tbody.innerHTML = sigs.map((s) => `
    <tr>
      <td class="muted">${fmtTime(s.created_at)}</td>
      <td class="pair-cell">${s.pair}</td>
      <td class="${s.side === "LONG" ? "side-long" : "side-short"}">${s.side}</td>
      <td>${isScalp
        ? `<span class="score-pill score-hi">${s.deal_pos != null ? "RSI " + s.deal_pos : "1R"}</span>`
        : `<span class="score-pill ${scoreClass(s.score)}">${s.score ?? "—"}</span>`}</td>
      <td class="num">${fmtPrice(s.pair, s.price)}</td>
      <td class="num muted">${fmtPrice(s.pair, s.sl)}</td>
      <td class="num muted">${fmtPrice(s.pair, s.tp)}</td>
      <td class="num">+${s.pips_tp}${(s.pair === "XAUUSD" || ["SPX500","NAS100","US30"].includes(s.pair)) ? "" : "p"}</td>
      <td class="num">${s.rr}</td>
      <td class="muted">${s.htf_bias || "—"}</td>
      <td><span class="st ${statusClass(s.status)}">${s.status.replace("_", " ")}</span>
          ${s.is_backtest ? "" : `<button class="m m-send" data-id="${s.id}" title="Re-send to Telegram">📤</button>`}</td>
      <td>${s.is_backtest
        ? `<span class="pill-src src-bt">backtest</span>`
        : `<span class="pill-src src-live">live</span>`}</td>
    </tr>`).join("");
  $("empty").classList.toggle("hidden", sigs.length > 0);

  renderPerf();
  renderEquity();
}

/* ------------------------------------------------------------------ equity */
function buildEquitySVG(series) {
  if (!series.length) return "";
  const W = 900, H = 320, L = 50, R = 20, T = 26, B = 44;
  const all = [];
  series.forEach((s) => s.pts.forEach((v) => all.push(v)));
  let ymin = Math.min(...all), ymax = Math.max(...all);
  const pad = (ymax - ymin) * 0.08 || 5;
  ymin -= pad; ymax += pad;
  if (ymin > 0) ymin = 0;
  const yp = (v) => T + (H - T - B) * (1 - (v - ymin) / (ymax - ymin));
  const parts = [];
  for (let g = 0; g <= Math.ceil(ymax) + 10; g += 10) {
    if (g < ymin || g > ymax) continue;
    parts.push(`<line x1="${L}" y1="${yp(g).toFixed(1)}" x2="${W - R}" y2="${yp(g).toFixed(1)}" stroke="#e2e8f0" stroke-width="1"/>`);
    parts.push(`<text x="${L - 8}" y="${(yp(g) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#64748b">${g}R</text>`);
  }
  if (ymin <= 0 && ymax >= 0) {
    parts.push(`<line x1="${L}" y1="${yp(0).toFixed(1)}" x2="${W - R}" y2="${yp(0).toFixed(1)}" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="4 3"/>`);
  }
  let ly = 14;
  series.forEach((s) => {
    const n = s.pts.length;
    const xx = (i) => L + (W - L - R) * (i / (n - 1 || 1));
    const coords = s.pts.map((v, i) => `${xx(i).toFixed(1)},${yp(v).toFixed(1)}`).join(" ");
    parts.push(`<polyline points="${coords}" fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`);
    parts.push(`<line x1="${L}" y1="${ly}" x2="${L + 18}" y2="${ly}" stroke="${s.color}" stroke-width="2.5"/>`);
    parts.push(`<text x="${L + 24}" y="${ly + 4}" font-size="11" fill="#0f172a">${s.label}</text>`);
    ly += 16;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px">${parts.join("")}</svg>`;
}

function renderEquity() {
  const isScalp = state.strategy === "scalp";
  const eq = isScalp ? (window.SCALP_BACKTEST_EQUITY || []) : (window.BACKTEST_EQUITY || []);
  const btTrades = isScalp ? (window.SCALP_BACKTEST_TRADES || []) : (window.BACKTEST_TRADES || []);
  const bt = btTrades.filter((t) => t.status === "hit_tp" || t.status === "hit_sl");
  if (!bt.length) { $("equity-cards").innerHTML = ""; $("equity-chart").innerHTML = ""; $("equity-note").innerHTML = ""; return; }

  const w = bt.filter((t) => t.status === "hit_tp").length;
  const l = bt.filter((t) => t.status === "hit_sl").length;
  const totalR = bt.reduce((a, t) => a + (t.status === "hit_tp" ? Number(t.rr) : -1), 0);
  const exp = bt.length ? totalR / bt.length : 0;
  const wr = bt.length ? (w / bt.length) * 100 : 0;
  let peak = eq.length ? eq[0][1] : 0, mdd = 0;
  for (const p of eq) { peak = Math.max(peak, p[1]); mdd = Math.min(mdd, p[1] - peak); }

  $("equity-cards").innerHTML = [
    ["Backtest trades", bt.length + `<small>60-day walk-forward</small>`],
    ["Win rate", wr.toFixed(0) + "%" + `<small>${w}W/${l}L</small>`],
    ["Total P&L", R(totalR) + `<small>risk-units</small>`],
    ["Expectancy", R(exp) + `<small>per trade</small>`],
    ["Max drawdown", R(mdd) + `<small>give-back</small>`],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  const series = [];
  if (eq.length) {
    series.push({ pts: eq.map((p) => p[1]), label: isScalp ? "Scalp backtest (1R)" : "Backtest (walk-forward)", color: "#059669" });
  }
  const live = state.signals
    .filter((s) => !s.is_backtest && strat(s) === state.strategy && (s.status === "hit_tp" || s.status === "hit_sl"))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  if (live.length) {
    let c = 0;
    const lp = [0];
    live.forEach((s) => { c += (s.status === "hit_tp" ? Number(s.rr) : -1); lp.push(c); });
    series.push({ pts: lp, label: "Live (forward test)", color: "#2563eb" });
  }

  $("equity-chart").innerHTML = buildEquitySVG(series);
  $("equity-note").innerHTML =
    `<b>Reading this:</b> the green line is the historical walk-forward backtest —
    each step up is a winning trade (+R:R), each step down a losing one (−1R). ` +
    (live.length ? `The blue line is your live forward-testing so far, on the same R scale.` :
    `Your live forward-testing line will appear here once real signals start closing.`) +
    ` Backtest trades are also in the history table above (tagged "backtest").`;
}
/* Manual TP/SL marking removed — outcomes are set ONLY by the scanner's
   automatic close-out (status is read-only for the browser). */
async function resendSignal(id) {
  const s = state.signals.find((x) => String(x.id) === String(id));
  if (!s) return;
  if (state.mode === "demo" || !state.client) {
    alert("Demo mode — connect Supabase to resend.");
    return;
  }
  const { error } = await state.client.from("signals").update({ resend: true }).eq("id", id);
  if (error) { alert("Resend failed: " + error.message); return; }
  const b = document.querySelector(`.m-send[data-id="${id}"]`);
  if (b) { b.textContent = "✓"; setTimeout(() => (b.textContent = "📤"), 2000); }
}

function exportCSV() {
  const head = ["created_at","pair","side","score","price","sl","tp","pips_tp","pips_sl","rr","htf_bias","status","reasons"];
  const rows = state.signals.map((s) => [
    s.created_at, s.pair, s.side, s.score, s.price, s.sl, s.tp, s.pips_tp,
    s.pips_sl, s.rr, s.htf_bias, s.status, JSON.stringify(s.reasons || []),
  ]);
  const csv = [head, ...rows]
    .map((r) => r.map((c) => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "smc-signals.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ------------------------------------------------------------------- demo */
function startDemo() {
  state.mode = "demo";
  state.signals = demoSignals().concat(backtestSignals()).concat(scalpBacktestSignals());
  $("mode-badge").textContent = "DEMO DATA";
  $("mode-badge").className = "badge badge-demo";
  $("foot-note").textContent = "Demo mode — connect Supabase to go live. (Sample data; not real signals.)";
  render();
}

/* ------------------------------------------------------------------- live */
async function startLive(config) {
  if (!window.supabase) { showErr("Supabase JS library failed to load (check internet / CDN)."); return; }
  try {
    state.client = window.supabase.createClient(config.url, config.key);
    const { data, error } = await state.client
      .from("signals").select("*").order("created_at", { ascending: false }).limit(500);
    if (error) throw error;
    state.mode = "live";
    state.signals = (data || []).map((d) => ({ ...d, source: "live" })).concat(backtestSignals()).concat(scalpBacktestSignals());
    $("mode-badge").textContent = "LIVE";
    $("mode-badge").className = "badge badge-live";
    $("foot-note").textContent = `Connected to ${config.url}`;
    render();
    subscribe();
  } catch (e) {
    showErr("Could not load from Supabase: " + (e.message || e));
    startDemo();
  }
}

function subscribe() {
  if (!state.client || state.channel) return;
  state.channel = state.client
    .channel("signals-stream")
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "signals" }, (payload) => {
      state.signals.unshift({ ...payload.new, source: "live" });
      render();
    })
    .on("postgres_changes", { event: "UPDATE", schema: "public", table: "signals" }, (payload) => {
      const i = state.signals.findIndex((s) => String(s.id) === String(payload.new.id));
      if (i >= 0) state.signals[i] = payload.new;
      render();
    })
    .subscribe();
}

/* ------------------------------------------------------------------ modal */
function showErr(msg) {
  const el = $("connect-err");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function openModal() {
  $("supa-url").value = localStorage.getItem(LS_URL) || "";
  $("supa-key").value = localStorage.getItem(LS_KEY) || "";
  $("connect-err").classList.add("hidden");
  $("modal").classList.remove("hidden");
}

/* -------------------------------------------------------------------- init */
function bind() {
  $("connect-btn").addEventListener("click", openModal);
  $("connect-cancel").addEventListener("click", () => $("modal").classList.add("hidden"));
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) $("modal").classList.add("hidden"); });
  $("connect-save").addEventListener("click", () => {
    const url = $("supa-url").value.trim();
    const key = $("supa-key").value.trim();
    if (!url || !key) { showErr("Both fields are required."); return; }
    localStorage.setItem(LS_URL, url);
    localStorage.setItem(LS_KEY, key);
    $("modal").classList.add("hidden");
    startLive({ url, key });
  });
  ["filter-pair", "filter-side", "filter-score", "filter-open", "filter-backtest"].forEach((id) =>
    $(id).addEventListener("change", render));
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.strategy = btn.dataset.strategy;
      render();
    });
  });
  $("csv-btn").addEventListener("click", exportCSV);
  document.querySelector("#table tbody").addEventListener("click", (e) => {
    const b = e.target.closest(".m-send");
    if (!b) return;
    resendSignal(b.dataset.id);
  });
}

bind();
const config = getConfig();
if (config && window.supabase) {
  startLive(config);
} else if (config) {
  window.addEventListener("load", () => {
    if (window.supabase) startLive(config); else startDemo();
  });
} else {
  startDemo();
}
