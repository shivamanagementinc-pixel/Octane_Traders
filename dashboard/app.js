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
const state = { signals: [], mode: "demo", client: null, channel: null };

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
  return state.signals.filter((s) =>
    (!pair || s.pair === pair) &&
    (!side || s.side === side) &&
    (s.score >= minScore) &&
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
  const p = computePerf(state.signals);
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

  $("perf-by-score").innerHTML = `<h3>By quality score</h3><div class="note">Does a higher score actually win more?</div>` +
    `<table class="mini"><thead><tr><th>Score</th><th>W</th><th>L</th><th>Win%</th></tr></thead><tbody>` +
    p.byScore.map((b) => `<tr><td>${b.label}</td><td class="num">${b.w}</td><td class="num">${b.l}</td><td class="num">${b.wr == null ? "—" : b.wr.toFixed(0) + "%"}</td></tr>`).join("") +
    `</tbody></table>`;
}

/* ------------------------------------------------------------------ render */
function render() {
  const all = state.signals;
  const sigs = filtered();
  $("count").textContent = `${sigs.length} signal${sigs.length === 1 ? "" : "s"}`;

  const open = all.filter((s) => s.status === "open").length;
  const hi = all.filter((s) => s.score >= 80).length;
  const wins = all.filter((s) => s.status === "hit_tp").length;
  const avg = all.length ? (all.reduce((a, s) => a + s.score, 0) / all.length).toFixed(1) : "—";
  $("stats").innerHTML = [
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
  const featured = stars.length ? stars.slice(0, 6) : sigs.filter((s) => s.status === "open").slice(0, 3);
  $("featured").innerHTML = featured.map((s) => `
    <div class="card ${s.score >= 80 ? "star" : ""}">
      <div class="top">
        <span class="pair">${s.pair} <span class="side-${s.side.toLowerCase()}">${s.side}</span></span>
        <span class="score-pill ${scoreClass(s.score)}">${s.score}</span>
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
      <td><span class="score-pill ${scoreClass(s.score)}">${s.score}</span></td>
      <td class="num">${fmtPrice(s.pair, s.price)}</td>
      <td class="num muted">${fmtPrice(s.pair, s.sl)}</td>
      <td class="num muted">${fmtPrice(s.pair, s.tp)}</td>
      <td class="num">+${s.pips_tp}${s.pair === "XAUUSD" ? "$" : "p"}</td>
      <td class="num">${s.rr}</td>
      <td class="muted">${s.htf_bias || "—"}</td>
      <td>${s.status === "open"
        ? `<div class="marks"><button class="m m-tp" data-id="${s.id}" data-st="hit_tp">TP</button><button class="m m-sl" data-id="${s.id}" data-st="hit_sl">SL</button><button class="m m-ex" data-id="${s.id}" data-st="expired">✕</button></div>`
        : `<span class="st ${statusClass(s.status)}">${s.status.replace("_", " ")}</span>`}</td>
    </tr>`).join("");
  $("empty").classList.toggle("hidden", sigs.length > 0);

  renderPerf();
}

/* -------------------------------------------------------------- outcomes */
async function markOutcome(id, status) {
  const s = state.signals.find((x) => String(x.id) === String(id));
  if (!s) return;
  if (state.mode === "demo" || !state.client) {
    s.status = status;
    render();
    return;
  }
  const { error } = await state.client.from("signals").update({ status }).eq("id", id);
  if (error) { alert("Update failed: " + error.message); return; }
  s.status = status;
  render();
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
  state.signals = demoSignals();
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
    state.signals = data || [];
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
      state.signals.unshift(payload.new);
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
  ["filter-pair", "filter-side", "filter-score", "filter-open"].forEach((id) =>
    $(id).addEventListener("change", render));
  $("csv-btn").addEventListener("click", exportCSV);
  document.querySelector("#table tbody").addEventListener("click", (e) => {
    const b = e.target.closest(".m");
    if (!b) return;
    markOutcome(b.dataset.id, b.dataset.st);
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
