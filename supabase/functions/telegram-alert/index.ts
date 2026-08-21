// ============================================================================
// Octane Traders — instant Telegram alerts (Supabase Edge Function)
//
// Fired by the database trigger (supabase/telegram-webhook.sql) the moment a
// row is INSERTed or UPDATEd in the `signals` table. This removes the 5-minute
// polling lag entirely:
//   * new signal  -> 🚨/🎯 alert instantly
//   * resend flag -> 🔄 RESEND alert instantly + clears the flag
//   * TP/SL hit   -> ✅/❌ alert instantly
//
// Deploy (CLI):
//   supabase functions deploy telegram-alert --no-verify-jwt
//   supabase secrets set TELEGRAM_BOT_TOKEN=<...> TELEGRAM_CHAT_ID=<...> \
//     SUPABASE_URL=<...> SUPABASE_SERVICE_ROLE_KEY=<...>
//
// (--no-verify-jwt is required because the trigger calls the function without
//  a browser JWT. Secrets are read server-side from env — nothing sensitive is
//  ever sent to or from the browser.)
// ============================================================================

const TG_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const TG_CHAT = Deno.env.get("TELEGRAM_CHAT_ID") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";

// Service key: newer projects expose SUPABASE_SECRET_KEYS (a JSON dict) and
// mark the legacy SUPABASE_SERVICE_ROLE_KEY as deprecated. Read either.
function resolveServiceKey(): string {
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;
  const dict = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (!dict) return "";
  try {
    const parsed = JSON.parse(dict);
    // common shapes: { default: "..." } | { service_role: "..." } | { "0": "..." }
    return parsed.default ?? parsed.service_role ?? Object.values(parsed)[0] ?? "";
  } catch {
    return "";
  }
}
const SUPABASE_SR_KEY = resolveServiceKey();

// Cooldown: don't re-alert the same pair+side within this many minutes on a
// brand-new signal (mirrors the old --telegram-cooldown-hours behaviour).
const COOLDOWN_MIN = 60;

// ---------------------------------------------------------------- formatting
function fmt(pair: string, v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  if (pair === "XAUUSD") return n.toFixed(2);
  if (pair.endsWith("JPY")) return n.toFixed(3);
  if (["SPX500", "NAS100", "US30"].includes(pair)) return n.toFixed(1);
  return n.toFixed(5);
}

function reasonLine(rec: Record<string, unknown>): string {
  const r = rec.reasons;
  if (Array.isArray(r) && r.length) return r.slice(0, 4).join(" · ");
  return "";
}

function signalText(rec: Record<string, unknown>): string {
  const strategy = (rec.strategy as string) ?? "smc";
  const pair = (rec.pair as string) ?? "?";
  const side = (rec.side as string) ?? "?";

  if (strategy === "scalp") {
    const unit = ["SPX500", "NAS100", "US30"].includes(pair) ? "pts" : "pips";
    return `🎯 ${pair} ${side} — SCALP (target ${rec.rr ?? "1"}R)\n` +
      `Entry ${fmt(pair, rec.price)} | SL ${fmt(pair, rec.sl)} | TP ${fmt(pair, rec.tp)}\n` +
      `5m RSI ${rec.deal_pos ?? "?"} · ${rec.htf_bias ?? "?"} 15m trend · ${rec.pips_tp ?? "?"} ${unit} target`;
  }

  const unit = pair === "XAUUSD" ? "$" : "pips";
  return `🚨 ${pair} ${side} — quality ${rec.score ?? "?"}/100\n` +
    `Entry ${fmt(pair, rec.price)} | SL ${fmt(pair, rec.sl)} | TP ${fmt(pair, rec.tp)}\n` +
    `Target +${rec.pips_tp ?? "?"} ${unit} | R:R ${rec.rr ?? "?"} | HTF ${rec.htf_bias ?? "?"}\n` +
    reasonLine(rec);
}

// ---------------------------------------------------------------- helpers
async function sendTelegram(text: string): Promise<boolean> {
  if (!TG_TOKEN || !TG_CHAT) return false;
  try {
    const r = await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: TG_CHAT, text }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

async function recentAlert(pair: string, side: string, strategy: string, excludeId: unknown): Promise<boolean> {
  if (!SUPABASE_URL || !SUPABASE_SR_KEY) return false;
  const since = new Date(Date.now() - COOLDOWN_MIN * 60000).toISOString();
  const q =
    `${SUPABASE_URL}/rest/v1/signals?pair=eq.${encodeURIComponent(pair)}` +
    `&side=eq.${encodeURIComponent(side)}&strategy=eq.${encodeURIComponent(strategy)}` +
    `&created_at=gte.${encodeURIComponent(since)}` +
    `&id=neq.${excludeId}&limit=1&select=id`;
  try {
    const r = await fetch(q, {
      headers: { apikey: SUPABASE_SR_KEY, Authorization: `Bearer ${SUPABASE_SR_KEY}` },
    });
    if (!r.ok) return false;
    const rows = await r.json();
    return Array.isArray(rows) && rows.length > 0;
  } catch {
    return false;
  }
}

async function clearResend(id: unknown): Promise<void> {
  if (!SUPABASE_URL || !SUPABASE_SR_KEY) return;
  try {
    await fetch(`${SUPABASE_URL}/rest/v1/signals?id=eq.${id}`, {
      method: "PATCH",
      headers: {
        apikey: SUPABASE_SR_KEY,
        Authorization: `Bearer ${SUPABASE_SR_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({ resend: false }),
    });
  } catch {
    /* ignore — the flag just stays set until next time */
  }
}

// -------------------------------------------------------------------- main
Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("ok", { status: 200 });

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  const type = body.type as string;
  const rec = (body.record ?? {}) as Record<string, unknown>;
  const old = (body.old_record ?? {}) as Record<string, unknown>;

  let text: string | null = null;

  if (type === "INSERT") {
    // New signal — alert instantly (with a same-pair+side+strategy cooldown to
    // avoid spam; swing and scalp never suppress each other).
    const recent = await recentAlert(
      (rec.pair as string) ?? "",
      (rec.side as string) ?? "",
      (rec.strategy as string) ?? "smc",
      rec.id,
    );
    if (!recent) text = signalText(rec);
  } else if (type === "UPDATE") {
    if (rec.resend === true && old.resend !== true) {
      // 📤 resend clicked in the dashboard — show the trade WITH its outcome
      // so a completed trade isn't mistaken for a live signal.
      const statusLine =
        rec.status === "hit_tp" ? "✅ OUTCOME: HIT TP"
        : rec.status === "hit_sl" ? "❌ OUTCOME: HIT SL"
        : rec.status === "expired" ? "⏳ OUTCOME: EXPIRED"
        : "🟢 STATUS: OPEN";
      text = "🔄 RESEND\n" + signalText(rec) + "\n" + statusLine;
      await clearResend(rec.id);
    } else if (
      rec.status &&
      rec.status !== old.status &&
      (rec.status === "hit_tp" || rec.status === "hit_sl")
    ) {
      // TP/SL hit (auto-marked by the scanner)
      const ok = rec.status === "hit_tp";
      text = `${ok ? "✅" : "❌"} ${rec.pair ?? "?"} ${rec.side ?? "?"}: ${
        ok ? "HIT TP" : "HIT SL"
      }`;
    }
  }

  if (text) await sendTelegram(text);
  return new Response("ok", { status: 200 });
});
