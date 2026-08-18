/* SMC Signal Dashboard — reads signals from Supabase (or shows demo data). */

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

/* --------------------------------------------------------------- demo data */
function demoSignals() {
  const now = Date.now();
  const mk = (o, minsAgo) => ({ created_at: new Date(now - minsAgo * 60000).toISOString(), status: "open", ...o });
  return [
    mk({ pair: "GBPJPY", side: "LONG", score: 93, price: 216.005, zone_lo: 215.999, zone_hi: 216.004, zone_type: "FVG", sl: 215.950, tp: 216.216, pips_tp: 21.1, pips_sl: 5.5, rr: 3.87, htf_bias: "bull", deal_pos: 48.6, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block", "inside FVG", "R:R 3.87"] }, 4),
    mk({ pair: "EURUSD", side: "LONG", score: 85, price: 1.15821, zone_lo: 1.15808, zone_hi: 1.15821, zone_type: "FVG", sl: 1.15758, tp: 1.16023, pips_tp: 20.2, pips_sl: 6.4, rr: 3.17, htf_bias: "bull", deal_pos: 100.0, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block", "inside FVG", "R:R 3.17"] }, 18),
    mk({ pair: "USDJPY", side: "LONG", score: 78, price: 159.694, zone_lo: 159.684, zone_hi: 159.710, zone_type: "OB", sl: 159.660, tp: 159.910, pips_tp: 21.6, pips_sl: 3.4, rr: 6.35, htf_bias: "bull", deal_pos: 62.0, reasons: ["HTF(1H) bullish", "sell-side liq swept + reclaim", "inside Order Block"] }, 32),
    mk({ pair: "GBPUSD", side: "LONG", score: 73, price: 1.35316, zone_lo: 1.35305, zone_hi: 1.35336, zone_type: "OB", sl: 1.35264, tp: 1.35525, pips_tp: 20.9, pips_sl: 5.2, rr: 4.02, htf_bias: "flat", deal_pos: 80.5, reasons: ["sell-side liq swept + reclaim", "inside Order Block", "inside FVG"] }, 41),
    mk({ pair: "USDCAD", side: "LONG", score: 73, price: 1.38736, zone_lo: 1.38670, zone_hi: 1.38787, zone_type: "OB", sl: 1.38646, tp: 1.39211, pips_tp: 47.5, pips_sl: 9.0, rr: 5.27, htf_bias: "flat", deal_pos: 79.0, reasons: ["sell-side liq swept + reclaim", "inside Order Block", "R:R 5.27"] }, 55),
    mk({ pair: "XAUUSD", side: "SHORT", score: 73, price: 4447.90, zone_lo: 4446.90, zone_hi: 4450.00, zone_type: "FVG", sl: 4455.83, tp: 4427.50, pips_tp: 20.4, pips_sl: 7.9, rr: 2.58, htf_bias: "flat", deal_pos: 32.2, reasons: ["buy-side liq swept + reclaim", "inside Order Block", "inside FVG"] }, 70),
    { pair: "EURJPY", side: "SHORT", score: 66, price: 184.856, zone_lo: 184.849, zone_hi: 184.880, zone_type: "OB", sl: 184.950, tp: 184.640, pips_tp: 21.6, pips_sl: 9.4, rr: 2.30, htf_bias: "bear", deal_pos: 45.0, status: "hit_sl", reasons: ["HTF bearish", "inside Order Block"], created_at: new Date(now - 90 * 60000).toISOString() },
    { pair: "AUDJPY", side: "LONG", score: 81, price: 113.542, zone_lo: 113.534, zone_hi: 113.553, zone_type: "FVG", sl: 113.500, tp: 113.760, pips_tp: 21.8, pips_sl: 4.2, rr: 5.19, htf_bias: "bull", deal_pos: 76.0, status: "hit_tp", reasons: ["HTF bullish", "sell-side liq swept + reclaim", "inside FVG"], created_at: new Date(now - 130 * 60000).toISOString() },
  ];
}

/* ------------------------------------------------------------------ state */
const state = { signals: [], mode: "demo", client: null, channel: null };

function getConfig() {
  const url = localStorage.getItem(LS_URL);
  const key = localStorage.getItem(LS_KEY);
  return url && key ? { url, key } : null;
}

/* ------------------------------------------------------------------ render */
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

function render() {
  const all = state.signals;
  const sigs = filtered();
  $("count").textContent = `${sigs.length} signal${sigs.length === 1 ? "" : "s"}`;

  // stats
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

  // pair dropdown
  const pairs = [...new Set(all.map((s) => s.pair))].sort();
  const cur = $("filter-pair").value;
  $("filter-pair").innerHTML = `<option value="">All</option>` +
    pairs.map((p) => `<option ${p === cur ? "selected" : ""}>${p}</option>`).join("");

  // featured cards
  const stars = sigs.filter((s) => s.score >= 80 && s.status === "open");
  const featured = stars.length ? stars.slice(0, 6) : sigs.slice(0, 3);
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

  // table
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
      <td><span class="st ${statusClass(s.status)}">${s.status}</span></td>
    </tr>`).join("");
  $("empty").classList.toggle("hidden", sigs.length > 0);
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
  if (!window.supabase) {
    showErr("Supabase JS library failed to load (check internet / CDN).");
    return;
  }
  try {
    state.client = window.supabase.createClient(config.url, config.key);
    const { data, error } = await state.client
      .from("signals").select("*").order("created_at", { ascending: false }).limit(300);
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
}

bind();
const config = getConfig();
if (config && window.supabase) {
  startLive(config);
} else if (config) {
  // CDN still loading — wait a tick, then try
  window.addEventListener("load", () => {
    if (window.supabase) startLive(config); else startDemo();
  });
} else {
  startDemo();
}
