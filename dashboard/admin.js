/* Octane Traders — Admin (accounts, risk, positions, master switch). */

const LS_URL = "smc.supa.url";
const LS_KEY = "smc.supa.key";
const $ = (id) => document.getElementById(id);

const state = { client: null, accounts: [], positions: [], enabled: true };

function getConfig() {
  const url = localStorage.getItem(LS_URL);
  const key = localStorage.getItem(LS_KEY);
  return url && key ? { url, key } : null;
}

function fmtTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
const fmtPx = (p, v) => (p === "XAUUSD" ? Number(v).toFixed(2) : p.endsWith("JPY") ? Number(v).toFixed(3) : Number(v).toFixed(5));

/* ---------------------------------------------------------------- loaders */
async function loadAll() {
  if (!state.client) return;
  const { data: accts } = await state.client.from("accounts").select("*").order("id");
  const { data: creds } = await state.client.from("account_credentials").select("account_id, mt5_login");
  const { data: pos } = await state.client.from("positions").select("*").eq("status", "open").order("opened_at", { ascending: false });
  const { data: settings } = await state.client.from("settings").select("*").eq("key", "trade_enabled");
  const today = new Date().toISOString().slice(0, 10);
  const { data: wins } = await state.client.from("signals").select("id").eq("status", "hit_tp").gte("created_at", today);
  const { data: losses } = await state.client.from("signals").select("id").eq("status", "hit_sl").gte("created_at", today);

  state.accounts = accts || [];
  state.positions = pos || [];
  state.enabled = settings && settings.length ? settings[0].value === true : true;
  const loginByAcc = {};
  (creds || []).forEach((c) => (loginByAcc[c.account_id] = c.mt5_login));

  $("kill-state").textContent = state.enabled ? "🟢 TRADING ENABLED" : "🔴 TRADING STOPPED";
  $("kill-state").className = "v " + (state.enabled ? "c-win" : "c-loss");
  $("kill-btn").textContent = state.enabled ? "Stop trading" : "Start trading";

  $("admin-stats").innerHTML = [
    ["Accounts", state.accounts.length],
    ["Open positions", state.positions.length],
    ["Wins today", (wins || []).length],
    ["Losses today", (losses || []).length],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  // accounts table
  $("accounts-table").querySelector("tbody").innerHTML = state.accounts.map((a) => `
    <tr>
      <td class="pair-cell">${a.name}</td>
      <td class="muted">${a.broker || "—"}</td>
      <td class="muted">${loginByAcc[a.id] || "—"}</td>
      <td><input class="risk-input" type="number" step="0.1" min="0.1" value="${a.risk_pct}" data-id="${a.id}"></td>
      <td><button class="m m-tgl ${a.active ? "on" : ""}" data-id="${a.id}" data-active="${a.active}">${a.active ? "ON" : "OFF"}</button></td>
      <td><button class="m m-del" data-id="${a.id}">delete</button></td>
    </tr>`).join("");
  $("accounts-empty").classList.toggle("hidden", state.accounts.length > 0);

  // positions table
  $("positions-table").querySelector("tbody").innerHTML = state.positions.map((p) => {
    const acc = state.accounts.find((a) => a.id === p.account_id);
    return `
    <tr>
      <td class="pair-cell">${acc ? acc.name : p.account_id}</td>
      <td class="muted">${p.ticket ?? "—"}</td>
      <td>${p.pair}</td>
      <td class="${p.side === "LONG" ? "side-long" : "side-short"}">${p.side}</td>
      <td class="num">${p.volume}</td>
      <td class="num muted">${fmtPx(p.pair, p.sl)}</td>
      <td class="num muted">${fmtPx(p.pair, p.tp)}</td>
      <td class="muted">${fmtTime(p.opened_at)}</td>
      <td><button class="m m-del" data-ticket="${p.ticket}" data-acc="${p.account_id}" data-act="close">close</button></td>
    </tr>`;
  }).join("");
  $("positions-empty").classList.toggle("hidden", state.positions.length > 0);
}

/* ---------------------------------------------------------------- actions */
async function toggleKill() {
  if (!state.client) return;
  await state.client.from("settings").update({ value: !state.enabled }).eq("key", "trade_enabled");
  loadAll();
}
async function closePosition(ticket, accId) {
  if (!state.client) return;
  await state.client.from("commands").insert({ action: "close_position", ticket: Number(ticket), account_id: accId });
  alert("Close command queued — the copier executes it within ~15s.");
  loadAll();
}
async function closeAll() {
  if (!state.client) return;
  await state.client.from("commands").insert({ action: "close_all" });
  alert("Close-all command queued for every active account.");
  loadAll();
}
async function updateRisk(id, val) {
  if (!state.client) return;
  await state.client.from("accounts").update({ risk_pct: Number(val) }).eq("id", id);
}
async function toggleAccount(id, cur) {
  if (!state.client) return;
  await state.client.from("accounts").update({ active: !cur }).eq("id", id);
  loadAll();
}
async function deleteAccount(id) {
  if (!state.client) return;
  if (!confirm("Delete this account (and its saved credentials)?")) return;
  await state.client.from("accounts").delete().eq("id", id);
  loadAll();
}
async function addAccount() {
  const name = $("a-name").value.trim();
  const login = $("a-login").value.trim();
  const pass = $("a-pass").value;
  const server = $("a-server").value.trim();
  if (!name || !login || !pass) { $("a-err").textContent = "Name, login and password are required."; $("a-err").classList.remove("hidden"); return; }
  const { data, error } = await state.client.from("accounts")
    .insert({ name, broker: $("a-broker").value.trim() || null, risk_pct: Number($("a-risk").value || 0.5), is_demo: true })
    .select("id").single();
  if (error) { $("a-err").textContent = error.message; $("a-err").classList.remove("hidden"); return; }
  // credentials go to the insert-only table (never readable from the browser)
  await state.client.from("account_credentials").insert({
    account_id: data.id, mt5_login: login, mt5_password: pass,
    mt5_server: server || null, symbol_suffix: $("a-suffix").value.trim() || "",
  });
  $("add-modal").classList.add("hidden");
  loadAll();
}

/* ------------------------------------------------------------------- setup */
function bind() {
  $("connect-btn").addEventListener("click", () => $("modal").classList.remove("hidden"));
  $("connect-cancel").addEventListener("click", () => $("modal").classList.add("hidden"));
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) $("modal").classList.add("hidden"); });
  $("connect-save").addEventListener("click", () => {
    const url = $("supa-url").value.trim(), key = $("supa-key").value.trim();
    if (!url || !key) return;
    localStorage.setItem(LS_URL, url); localStorage.setItem(LS_KEY, key);
    $("modal").classList.add("hidden");
    startLive({ url, key });
  });

  $("kill-btn").addEventListener("click", toggleKill);
  $("close-all-btn").addEventListener("click", closeAll);
  $("add-account-btn").addEventListener("click", () => { $("add-modal").classList.remove("hidden"); $("a-err").classList.add("hidden"); });
  $("a-cancel").addEventListener("click", () => $("add-modal").classList.add("hidden"));
  $("a-save").addEventListener("click", addAccount);

  $("accounts-table").addEventListener("click", (e) => {
    const b = e.target.closest(".m");
    if (!b) return;
    if (b.classList.contains("m-tgl")) toggleAccount(Number(b.dataset.id), b.dataset.active === "true");
    if (b.classList.contains("m-del")) deleteAccount(Number(b.dataset.id));
  });
  $("accounts-table").addEventListener("change", (e) => {
    if (e.target.classList.contains("risk-input")) updateRisk(Number(e.target.dataset.id), e.target.value);
  });
  $("positions-table").addEventListener("click", (e) => {
    const b = e.target.closest(".m");
    if (b && b.dataset.act === "close") closePosition(b.dataset.ticket, Number(b.dataset.acc));
  });
}

async function startLive(config) {
  if (!window.supabase) return;
  state.client = window.supabase.createClient(config.url, config.key);
  $("mode-badge").textContent = "LIVE";
  $("mode-badge").className = "badge badge-live";
  loadAll();
}

bind();
const config = getConfig();
if (config && window.supabase) startLive(config);
else if (config) window.addEventListener("load", () => window.supabase && startLive(config));
