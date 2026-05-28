/**
 * Kodi-AI device-code relay (Cloudflare Worker).
 *
 * This is the USER'S OWN Worker (deployed on their free Cloudflare account).
 * It brokers an OAuth-device-code-style pairing between a Kodi add-on running
 * on a TV and the user's phone, so the user never has to type a bot token or
 * an OpenRouter key on a TV remote.
 *
 * Flow:
 *   1. Kodi POSTs /api/device/new with a setup_secret it generated + owns.
 *      The Worker mints a short user_code + an opaque device_code, stores a
 *      pending session in KV (TTL 300s), and returns both to Kodi.
 *   2. Kodi shows the user_code on the TV; the user opens this Worker's URL
 *      on their phone, types the user_code, fills the form (bot token,
 *      OpenRouter key, mode), and submits.
 *   3. The phone POSTs /api/submit. The Worker re-validates the bot token to
 *      capture the bot @username and marks the session "ready" (TTL 120s).
 *      The user_code mapping is left to expire on its own TTL (not deleted)
 *      so an idempotent re-submit (double-tap / retry) can still resolve it
 *      and return the same success; the per-code submit cap bounds abuse.
 *   4. Kodi long-polls /api/device/poll (device_code in the Authorization
 *      header, NOT the URL) until it sees "ready", reads the payload, and the
 *      Worker tombstones the KV key on read.
 *
 * SECURITY DISCIPLINE (hard rules — see DEPLOY.md + PRIVACY.md):
 *   - NEVER console.log a bot token, OpenRouter key, device_code, setup_secret,
 *     user_code, or any URL/string containing them. (We do not console.log at
 *     all in the request hot path.)
 *   - Secrets transit KV transiently: pending TTL 300s, ready TTL 120s,
 *     tombstone TTL 60s. device_code travels in the Authorization header so it
 *     never lands in Cloudflare's URL access logs.
 *   - Upstream error bodies (Telegram / OpenRouter) are NEVER echoed verbatim;
 *     the Telegram getMe error body embeds the bot URL+token, so we map every
 *     upstream failure to a fixed generic error string.
 *
 * KV namespace binding: KODI_AI_SESSIONS
 *   dc:<device_code>  -> JSON session  (pending | ready | consumed)
 *   uc:<user_code>    -> device_code   (lookup; expires on TTL, kept after
 *                                        submit so re-submits stay idempotent)
 *   submitcount:<user_code> -> stringified int (per-code submit attempt cap)
 */

// Unambiguous user_code alphabet: no 0/O, 1/I/L.
const USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const USER_CODE_LEN = 8; // formatted XXXX-XXXX
const SESSION_TTL_S = 300; // pending session lifetime
const READY_TTL_S = 120; // ready payload lifetime (short — secrets inside)
const TOMBSTONE_TTL_S = 60; // consumed marker after Kodi reads the payload
const MAX_SUBMIT_ATTEMPTS = 5; // per user_code

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function htmlResponse(html, status = 200) {
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

/** base64url-encode a Uint8Array (no padding). */
function base64url(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Generate a formatted user_code like "AB3D-7K2M" from the safe alphabet. */
function generateUserCode() {
  const raw = new Uint8Array(USER_CODE_LEN);
  crypto.getRandomValues(raw);
  let out = "";
  for (let i = 0; i < USER_CODE_LEN; i++) {
    out += USER_CODE_ALPHABET[raw[i] % USER_CODE_ALPHABET.length];
  }
  return out.slice(0, 4) + "-" + out.slice(4);
}

/** Generate an opaque device_code: 32 random bytes, base64url (~43 chars). */
function generateDeviceCode() {
  const raw = new Uint8Array(32);
  crypto.getRandomValues(raw);
  return base64url(raw);
}

/** Normalize a user-typed code: uppercase, strip spaces, ensure XXXX-XXXX. */
function normalizeUserCode(input) {
  if (typeof input !== "string") return "";
  let s = input.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (s.length !== USER_CODE_LEN) return "";
  return s.slice(0, 4) + "-" + s.slice(4);
}

// M2 — reject oversized bodies before buffering. Every legitimate request
// here is a tiny JSON object (a code, a token, a key); a 16 KB cap is
// generous and prevents a large-body upload from wasting free-tier
// CPU/memory. Callers map a null return to a bad_request response.
const MAX_BODY_BYTES = 16384;

async function readJsonBody(request) {
  const lenHeader = request.headers.get("Content-Length");
  if (lenHeader) {
    const len = parseInt(lenHeader, 10);
    if (Number.isFinite(len) && len > MAX_BODY_BYTES) {
      return null;
    }
  }
  try {
    return await request.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Upstream validation (server-side; bodies NEVER echoed)
// ---------------------------------------------------------------------------

/**
 * Call Telegram getMe for `botToken`. Returns { ok, username } on success,
 * { ok:false, error } otherwise. The upstream error body embeds the bot URL
 * (which contains the token) so we NEVER surface it — only a generic string.
 */
async function validateTelegram(botToken) {
  if (typeof botToken !== "string" || !botToken.trim()) {
    return { ok: false, error: "invalid_token" };
  }
  let resp;
  try {
    resp = await fetch(
      "https://api.telegram.org/bot" + botToken.trim() + "/getMe",
      { method: "GET" }
    );
  } catch {
    // Network/DNS error. Do not include the exception (it may carry the URL).
    return { ok: false, error: "telegram_unreachable" };
  }
  let body;
  try {
    body = await resp.json();
  } catch {
    return { ok: false, error: "invalid_token" };
  }
  // Telegram returns ok:false (usually 401) for a bad token. We deliberately
  // ignore body.description (it can echo the request URL on rare paths).
  if (!resp.ok || !body || body.ok !== true) {
    return { ok: false, error: "invalid_token" };
  }
  const username = (body.result && body.result.username) || "";
  if (!username) {
    return { ok: false, error: "invalid_token" };
  }
  return { ok: true, username };
}

/**
 * Validate an OpenRouter key via GET /api/v1/key. The key is NEVER logged.
 *
 * M3 — This replaces the old billable 1-token chat completion (which also
 * pinned a hardcoded model that could be retired, breaking all validations).
 * GET /api/v1/key is free, generates nothing, and has no model dependency.
 * It returns the key's metadata (incl. limit/usage) when the key is valid.
 */
async function validateOpenRouter(apiKey) {
  if (typeof apiKey !== "string" || !apiKey.trim()) {
    return { ok: false, error: "invalid_key" };
  }
  let resp;
  try {
    resp = await fetch("https://openrouter.ai/api/v1/key", {
      method: "GET",
      headers: { Authorization: "Bearer " + apiKey.trim() },
    });
  } catch {
    return { ok: false, error: "validation_failed" };
  }
  if (resp.status === 401) return { ok: false, error: "invalid_key" };
  if (resp.status >= 200 && resp.status < 300) {
    // Best-effort: inspect remaining credit if OpenRouter reports it. A
    // present-and-non-positive limit_remaining means the key is valid but
    // exhausted — surface no_credit so the phone tells the user to top up.
    try {
      const body = await resp.json();
      const data = body && body.data;
      if (
        data &&
        typeof data.limit_remaining === "number" &&
        data.limit_remaining <= 0
      ) {
        return { ok: false, error: "no_credit" };
      }
    } catch {
      // Body parse failure on a 2xx — treat the key as valid; the Kodi-side
      // validation (lib/llm/client.py) is the authoritative check anyway.
    }
    return { ok: true };
  }
  return { ok: false, error: "validation_failed" };
}

// ---------------------------------------------------------------------------
// API endpoints
// ---------------------------------------------------------------------------

/** POST /api/device/new — called by Kodi. Body: { setup_secret }. */
async function handleDeviceNew(request, env) {
  const body = await readJsonBody(request);
  const setupSecret =
    body && typeof body.setup_secret === "string" ? body.setup_secret : "";
  if (!setupSecret) {
    return jsonResponse({ error: "missing_setup_secret" }, 400);
  }

  const userCode = generateUserCode();
  const deviceCode = generateDeviceCode();
  const session = {
    status: "pending",
    user_code: userCode,
    setup_secret: setupSecret,
    created: Date.now(),
  };

  await env.KODI_AI_SESSIONS.put("dc:" + deviceCode, JSON.stringify(session), {
    expirationTtl: SESSION_TTL_S,
  });
  await env.KODI_AI_SESSIONS.put("uc:" + userCode, deviceCode, {
    expirationTtl: SESSION_TTL_S,
  });

  return jsonResponse({
    user_code: userCode,
    device_code: deviceCode,
    expires_in: SESSION_TTL_S,
  });
}

/** POST /api/validate-telegram — phone. Body: { bot_token }. */
async function handleValidateTelegram(request, env) {
  const body = await readJsonBody(request);
  const botToken =
    body && typeof body.bot_token === "string" ? body.bot_token : "";
  const result = await validateTelegram(botToken);
  return jsonResponse(result);
}

/** POST /api/validate-openrouter — phone. Body: { api_key }. */
async function handleValidateOpenRouter(request, env) {
  const body = await readJsonBody(request);
  const apiKey = body && typeof body.api_key === "string" ? body.api_key : "";
  const result = await validateOpenRouter(apiKey);
  return jsonResponse(result);
}

/**
 * POST /api/submit — phone. Body: { user_code, bot_token, openrouter_key, mode }.
 *
 * - Per-user_code attempt cap (>5 deletes the session, returns too_many_attempts).
 * - Idempotent: a repeated submit that matches an already-ready session returns
 *   the same success without re-validating (the user_code mapping is kept until
 *   its TTL so the retry can resolve the device_code).
 * - On success: marks session ready (TTL 120s); the user_code mapping is left
 *   to expire on its own TTL (not deleted) to keep re-submits idempotent.
 */
async function handleSubmit(request, env) {
  const body = await readJsonBody(request);
  if (!body) return jsonResponse({ ok: false, error: "bad_request" }, 400);

  const userCode = normalizeUserCode(body.user_code);
  const botToken =
    typeof body.bot_token === "string" ? body.bot_token.trim() : "";
  const openrouterKey =
    typeof body.openrouter_key === "string" ? body.openrouter_key.trim() : "";
  let mode =
    typeof body.mode === "string" ? body.mode.trim().toLowerCase() : "auto";
  if (mode !== "auto" && mode !== "manual") mode = "auto";

  if (!userCode) {
    return jsonResponse({ ok: false, error: "code_expired" });
  }

  // Per-code submit attempt cap. Increment FIRST so even malformed submits
  // count against the cap and a brute-force on a live code is bounded.
  const countKey = "submitcount:" + userCode;
  const prevCountRaw = await env.KODI_AI_SESSIONS.get(countKey);
  const prevCount = prevCountRaw ? parseInt(prevCountRaw, 10) || 0 : 0;
  const newCount = prevCount + 1;

  // Resolve the session up front (used for both cap-cleanup and normal flow).
  const deviceCode = await env.KODI_AI_SESSIONS.get("uc:" + userCode);

  if (newCount > MAX_SUBMIT_ATTEMPTS) {
    // Burn the session entirely — this code is now poisoned.
    if (deviceCode) {
      await env.KODI_AI_SESSIONS.delete("dc:" + deviceCode);
    }
    await env.KODI_AI_SESSIONS.delete("uc:" + userCode);
    await env.KODI_AI_SESSIONS.delete(countKey);
    return jsonResponse({ ok: false, error: "too_many_attempts" });
  }
  // Persist the incremented counter, bounded to the session lifetime.
  await env.KODI_AI_SESSIONS.put(countKey, String(newCount), {
    expirationTtl: SESSION_TTL_S,
  });

  if (!deviceCode) {
    return jsonResponse({ ok: false, error: "code_expired" });
  }

  const sessionRaw = await env.KODI_AI_SESSIONS.get("dc:" + deviceCode);
  if (!sessionRaw) {
    return jsonResponse({ ok: false, error: "code_expired" });
  }
  let session;
  try {
    session = JSON.parse(sessionRaw);
  } catch {
    return jsonResponse({ ok: false, error: "code_expired" });
  }

  // Idempotent double-submit: if already ready with matching token, return the
  // same success without re-hitting Telegram. (Phone retried / double-tapped.)
  if (
    session.status === "ready" &&
    session.data &&
    session.data.bot_token === botToken
  ) {
    const u = session.data.bot_username || "";
    return jsonResponse({
      ok: true,
      bot_username: u,
      pair_url: "https://t.me/" + u + "?start=" + session.setup_secret,
    });
  }

  if (!botToken || !openrouterKey) {
    return jsonResponse({ ok: false, error: "missing_fields" });
  }

  // Re-validate the bot token to capture the username authoritatively.
  const tg = await validateTelegram(botToken);
  if (!tg.ok) {
    return jsonResponse({ ok: false, error: "invalid_token" });
  }
  const username = tg.username;

  const readySession = {
    status: "ready",
    data: {
      bot_token: botToken,
      openrouter_key: openrouterKey,
      mode,
      bot_username: username,
    },
    setup_secret: session.setup_secret,
  };
  await env.KODI_AI_SESSIONS.put(
    "dc:" + deviceCode,
    JSON.stringify(readySession),
    { expirationTtl: READY_TTL_S }
  );
  // H1 — Do NOT delete uc:<user_code> here. If we delete it, a phone
  // double-tap or network-retry of an already-succeeded submit can no
  // longer resolve the device_code (uc: is gone) and the idempotent
  // re-submit branch above (session.status === "ready") becomes dead
  // code — the retry would return code_expired even though setup worked.
  // Instead we let uc: expire naturally via its SESSION_TTL_S. The submit
  // cap (MAX_SUBMIT_ATTEMPTS per code) still bounds brute-force abuse.

  return jsonResponse({
    ok: true,
    bot_username: username,
    pair_url: "https://t.me/" + username + "?start=" + session.setup_secret,
  });
}

/**
 * GET /api/device/poll — called by Kodi. device_code in Authorization: Bearer.
 *
 * pending -> { status:"pending" }
 * ready   -> { status:"ready", data:{...}, setup_secret } AND tombstone-on-read.
 * missing -> { status:"expired" }
 */
async function handleDevicePoll(request, env) {
  const authHeader = request.headers.get("Authorization") || "";
  const bearerMatch = authHeader.match(/^Bearer\s+(.+)$/);
  const deviceCode = bearerMatch ? bearerMatch[1].trim() : "";
  if (!deviceCode) {
    return jsonResponse({ status: "expired" });
  }

  const sessionRaw = await env.KODI_AI_SESSIONS.get("dc:" + deviceCode);
  if (!sessionRaw) {
    return jsonResponse({ status: "expired" });
  }
  let session;
  try {
    session = JSON.parse(sessionRaw);
  } catch {
    return jsonResponse({ status: "expired" });
  }

  if (session.status === "ready") {
    // Tombstone-on-read: overwrite with a short-lived consumed marker AND
    // issue a delete. Belt-and-suspenders so a re-poll can't re-read secrets.
    await env.KODI_AI_SESSIONS.put(
      "dc:" + deviceCode,
      JSON.stringify({ status: "consumed" }),
      { expirationTtl: TOMBSTONE_TTL_S }
    );
    await env.KODI_AI_SESSIONS.delete("dc:" + deviceCode);
    return jsonResponse({
      status: "ready",
      data: session.data,
      setup_secret: session.setup_secret,
    });
  }

  if (session.status === "consumed") {
    // Already read once — treat as expired for any later poll.
    return jsonResponse({ status: "expired" });
  }

  return jsonResponse({ status: "pending" });
}

// ---------------------------------------------------------------------------
// Mobile page (inline, self-contained)
// ---------------------------------------------------------------------------

function renderPage(prefillCode) {
  const safePrefill = (prefillCode || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Kodi-AI Setup</title>
<style>
  :root { --bg:#0a0e1a; --card:#121829; --cyan:#00d4ff; --dim:#7f93b5;
          --ok:#00e676; --err:#ff5c5c; --txt:#eaf2ff; --line:#22304d; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--txt);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         line-height:1.5; padding:24px 16px 64px; }
  .wrap { max-width:440px; margin:0 auto; }
  h1 { font-size:1.5rem; margin:0 0 4px; }
  h1 .ai { color:var(--cyan); }
  .sub { color:var(--dim); margin:0 0 24px; font-size:.95rem; }
  .card { background:var(--card); border:1px solid var(--line);
          border-radius:14px; padding:18px; margin-bottom:18px; }
  .card h2 { font-size:1.05rem; margin:0 0 6px; }
  .step-note { color:var(--dim); font-size:.85rem; margin:0 0 12px; }
  label { display:block; font-size:.85rem; color:var(--dim); margin:14px 0 6px; }
  input[type=text], input[type=password] {
    width:100%; padding:13px 12px; font-size:1rem; color:var(--txt);
    background:#0c1320; border:1px solid var(--line); border-radius:10px;
    outline:none; }
  input:focus { border-color:var(--cyan); }
  #code { letter-spacing:3px; text-transform:uppercase; font-weight:700;
          text-align:center; font-size:1.3rem; }
  button { width:100%; padding:14px; font-size:1rem; font-weight:700;
           color:#06121f; background:var(--cyan); border:0; border-radius:11px;
           margin-top:16px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  button.secondary { background:#1b2740; color:var(--cyan);
                     border:1px solid var(--line); }
  .inline-btn { margin-top:8px; }
  .msg { font-size:.85rem; margin-top:8px; min-height:1.1em; }
  .msg.ok { color:var(--ok); }
  .msg.err { color:var(--err); }
  .radios { display:flex; gap:10px; margin-top:10px; }
  .radios label { flex:1; margin:0; padding:13px; text-align:center;
                  border:1px solid var(--line); border-radius:10px;
                  color:var(--txt); cursor:pointer; }
  .radios input { display:none; }
  .radios input:checked + span { color:var(--cyan); font-weight:700; }
  .radios label:has(input:checked) { border-color:var(--cyan); }
  .hidden { display:none; }
  a { color:var(--cyan); }
  .ok-big { font-size:1.1rem; color:var(--ok); margin:8px 0 4px; }
  .finish { display:block; text-align:center; text-decoration:none;
            padding:15px; font-weight:700; color:#06121f; background:var(--cyan);
            border-radius:11px; margin-top:18px; }
  .warn { color:var(--dim); font-size:.8rem; margin-top:12px; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Kodi<span class="ai">-AI</span> Setup</h1>
  <p class="sub">Pair your TV from your phone. Nothing is stored on a server.</p>

  <!-- Step A: code -->
  <div class="card" id="stepA">
    <h2>Enter your TV code</h2>
    <p class="step-note">Your TV shows an 8-character code. Type it below.</p>
    <label for="code">Code</label>
    <input id="code" type="text" inputmode="text" autocomplete="off"
           maxlength="9" placeholder="XXXX-XXXX" value="${safePrefill}">
    <button id="continueBtn">Continue</button>
    <div class="msg err" id="codeMsg"></div>
  </div>

  <!-- Step B: form -->
  <div class="card hidden" id="stepB">
    <h2>Telegram bot</h2>
    <p class="step-note">Open <b>@BotFather</b> in Telegram, send <b>/newbot</b>,
      follow the prompts, and copy the token it gives you.</p>
    <label for="botToken">Bot token</label>
    <input id="botToken" type="text" autocomplete="off" placeholder="123456:ABC...">
    <button class="secondary inline-btn" id="validateTgBtn">Validate token</button>
    <div class="msg" id="tgMsg"></div>
  </div>

  <div class="card hidden" id="stepB2">
    <h2>OpenRouter key</h2>
    <p class="step-note">Get a key at <b>openrouter.ai/keys</b>
      (about $5 of credit lasts a long time).</p>
    <label for="orKey">API key</label>
    <input id="orKey" type="password" autocomplete="off" placeholder="sk-or-...">
    <button class="secondary inline-btn" id="validateOrBtn">Validate key</button>
    <div class="msg" id="orMsg"></div>
  </div>

  <div class="card hidden" id="stepB3">
    <h2>Agent mode</h2>
    <p class="step-note">Auto applies safe fixes for you. Manual asks first.</p>
    <div class="radios">
      <label><input type="radio" name="mode" value="auto" checked>
        <span>Auto (recommended)</span></label>
      <label><input type="radio" name="mode" value="manual">
        <span>Manual</span></label>
    </div>
    <button id="sendBtn">Send to TV</button>
    <div class="msg err" id="sendMsg"></div>
  </div>

  <!-- Step C: success -->
  <div class="card hidden" id="stepC">
    <h2>Sent!</h2>
    <p class="ok-big">Details sent to your TV.</p>
    <p class="step-note">Finishing there now. Your TV will ask you to confirm
      the bot, then show <b>Ready</b>.</p>
    <a class="finish" id="finishLink" href="#">Open Telegram to finish pairing</a>
    <p class="warn">Tap this AFTER your TV shows "Ready".</p>
  </div>
</div>

<script>
(function () {
  var state = { code: "", botToken: "", orKey: "", tgValid: false, orValid: false };

  function $(id) { return document.getElementById(id); }
  function show(id) { $(id).classList.remove("hidden"); }
  function setMsg(id, text, cls) {
    var el = $(id);
    el.textContent = text || "";
    el.className = "msg" + (cls ? " " + cls : "");
  }
  function normCode(v) {
    var s = (v || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (s.length > 8) s = s.slice(0, 8);
    return s.length > 4 ? s.slice(0, 4) + "-" + s.slice(4) : s;
  }

  $("code").addEventListener("input", function (e) {
    e.target.value = normCode(e.target.value);
  });

  async function postJson(url, payload) {
    var r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return r.json();
  }

  var TG_ERRORS = {
    invalid_token: "That token did not work. Re-copy it from @BotFather.",
    telegram_unreachable: "Could not reach Telegram. Check your connection and retry.",
  };
  var OR_ERRORS = {
    invalid_key: "Invalid key. Re-copy it from openrouter.ai/keys.",
    no_credit: "No credit on this key. Add credit at openrouter.ai/credits.",
    validation_failed: "Could not validate the key. Try again in a moment.",
  };

  $("continueBtn").addEventListener("click", function () {
    var c = normCode($("code").value);
    if (c.length !== 9) {
      setMsg("codeMsg", "Enter the full 8-character code.", "err");
      return;
    }
    state.code = c;
    setMsg("codeMsg", "");
    $("continueBtn").disabled = true;
    $("code").disabled = true;
    show("stepB"); show("stepB2"); show("stepB3");
  });

  $("validateTgBtn").addEventListener("click", async function () {
    var t = $("botToken").value.trim();
    if (!t) { setMsg("tgMsg", "Paste your bot token first.", "err"); return; }
    setMsg("tgMsg", "Checking...", "");
    $("validateTgBtn").disabled = true;
    try {
      var res = await postJson("/api/validate-telegram", { bot_token: t });
      if (res.ok) {
        state.botToken = t; state.tgValid = true;
        setMsg("tgMsg", "Verified bot: @" + res.username, "ok");
      } else {
        state.tgValid = false;
        setMsg("tgMsg", TG_ERRORS[res.error] || "Validation failed.", "err");
      }
    } catch (e) {
      setMsg("tgMsg", "Network error. Try again.", "err");
    }
    $("validateTgBtn").disabled = false;
  });

  $("validateOrBtn").addEventListener("click", async function () {
    var k = $("orKey").value.trim();
    if (!k) { setMsg("orMsg", "Paste your OpenRouter key first.", "err"); return; }
    setMsg("orMsg", "Checking...", "");
    $("validateOrBtn").disabled = true;
    try {
      var res = await postJson("/api/validate-openrouter", { api_key: k });
      if (res.ok) {
        state.orKey = k; state.orValid = true;
        setMsg("orMsg", "Key is valid.", "ok");
      } else {
        state.orValid = false;
        setMsg("orMsg", OR_ERRORS[res.error] || "Validation failed.", "err");
      }
    } catch (e) {
      setMsg("orMsg", "Network error. Try again.", "err");
    }
    $("validateOrBtn").disabled = false;
  });

  $("sendBtn").addEventListener("click", async function () {
    var t = state.botToken || $("botToken").value.trim();
    var k = state.orKey || $("orKey").value.trim();
    var mode = (document.querySelector('input[name="mode"]:checked') || {}).value || "auto";
    if (!t) { setMsg("sendMsg", "Validate your bot token first.", "err"); return; }
    if (!k) { setMsg("sendMsg", "Validate your OpenRouter key first.", "err"); return; }
    setMsg("sendMsg", "Sending...", "");
    $("sendBtn").disabled = true;
    try {
      var res = await postJson("/api/submit", {
        user_code: state.code, bot_token: t, openrouter_key: k, mode: mode,
      });
      if (res.ok) {
        var link = $("finishLink");
        if (res.pair_url) link.setAttribute("href", res.pair_url);
        $("stepB").classList.add("hidden");
        $("stepB2").classList.add("hidden");
        $("stepB3").classList.add("hidden");
        show("stepC");
      } else {
        var map = {
          code_expired: "Your TV code expired. Start setup again on the TV.",
          too_many_attempts: "Too many attempts. Start setup again on the TV.",
          invalid_token: "The bot token did not validate. Check it and retry.",
          missing_fields: "Please fill in both the bot token and the key.",
        };
        setMsg("sendMsg", map[res.error] || "Could not send. Try again.", "err");
        $("sendBtn").disabled = false;
      }
    } catch (e) {
      setMsg("sendMsg", "Network error. Try again.", "err");
      $("sendBtn").disabled = false;
    }
  });
})();
</script>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // Mobile page (same-origin; pre-fill code from ?code=).
    if (method === "GET" && (path === "/" || path === "")) {
      return htmlResponse(renderPage(url.searchParams.get("code") || ""));
    }

    if (path === "/api/device/new" && method === "POST") {
      return handleDeviceNew(request, env);
    }
    if (path === "/api/validate-telegram" && method === "POST") {
      return handleValidateTelegram(request, env);
    }
    if (path === "/api/validate-openrouter" && method === "POST") {
      return handleValidateOpenRouter(request, env);
    }
    if (path === "/api/submit" && method === "POST") {
      return handleSubmit(request, env);
    }
    if (path === "/api/device/poll" && method === "GET") {
      return handleDevicePoll(request, env);
    }

    return jsonResponse({ error: "not_found" }, 404);
  },
};
