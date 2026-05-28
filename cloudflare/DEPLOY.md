# Deploy your Kodi-AI relay (Cloudflare Worker)

The relay is a tiny Cloudflare Worker **you deploy on your own free
Cloudflare account**. It lets you set up Kodi-AI from your phone instead of
typing a bot token and an API key on a TV remote.

Your secrets (bot token, OpenRouter key) pass through this Worker only
**transiently**: they live in Cloudflare KV for at most 2 minutes, are
deleted the moment your TV reads them, and are **never logged**. It is your
relay, on your account — no third party is involved. See `../PRIVACY.md`.

This is a one-time, ~5-minute setup.

---

## 0. Prerequisites

- A free [Cloudflare account](https://dash.cloudflare.com/sign-up).
- [Node.js](https://nodejs.org/) installed on your computer (for `wrangler`,
  Cloudflare's CLI). Any recent LTS is fine.

## 1. Install wrangler

```bash
npm install -g wrangler
```

(Or use `npx wrangler ...` in place of `wrangler ...` below if you prefer not
to install globally.)

## 2. Log in to Cloudflare

```bash
wrangler login
```

This opens a browser window — approve the access request.

## 3. Get the relay files

Clone (or download) this repo and `cd` into the `cloudflare/` folder:

```bash
git clone https://github.com/Stigmavlc/Kodi-AI.git
cd Kodi-AI/cloudflare
```

You need `worker.js` and `wrangler.toml` — they are both here.

## 4. Create the KV namespace

The Worker stores short-lived pairing sessions in a Cloudflare KV namespace.

```bash
wrangler kv namespace create KODI_AI_SESSIONS
```

It prints something like:

```
[[kv_namespaces]]
binding = "KODI_AI_SESSIONS"
id = "abcdef0123456789abcdef0123456789"
```

Copy the `id` value.

## 5. Paste the id into wrangler.toml

Open `wrangler.toml` and replace `REPLACE_WITH_KV_NAMESPACE_ID` with the id
you just copied:

```toml
[[kv_namespaces]]
binding = "KODI_AI_SESSIONS"
id = "abcdef0123456789abcdef0123456789"
```

Leave `binding = "KODI_AI_SESSIONS"` exactly as-is.

## 6. Deploy

```bash
wrangler deploy
```

It prints your Worker URL, e.g.:

```
https://kodi-ai-relay.your-subdomain.workers.dev
```

Copy that URL.

## 7. Tell Kodi about it (only if not already pre-filled)

The addon ships with the project's relay URL as the **default**, so most
installs need nothing here. Check first:

**Kodi -> Settings (gear) -> Add-ons -> Kodi-AI -> Configure -> Advanced ->
Relay URL**.

- If it already shows a `https://kodi-ai-relay.*.workers.dev` URL -> you're
  done, skip this step.
- If it's **empty** (can happen on installs that ran an older version which
  saved an empty value before the default existed), or if you deployed your
  **own** relay under a different subdomain, paste your URL there and Save.

That's it. Now go to **Configure -> Telegram -> "Set up via phone"** and
follow the on-screen code.

---

## Testing it (optional)

### Local dev

You can run the Worker locally before deploying:

```bash
wrangler dev
```

This serves it at `http://localhost:8787`. Open that URL in a browser to see
the setup page. Note: `wrangler dev` uses a local KV simulation by default,
which is fine for poking at the endpoints.

### curl smoke test

See `test.http` in this folder for ready-to-paste curl commands that exercise
each endpoint (`/api/device/new`, `/api/device/poll`, `/api/submit`, the two
validate endpoints). Replace the host with your `wrangler dev` localhost or
your deployed `*.workers.dev` URL.

The Worker is **not** covered by the Python test suite — it is tested
manually with `wrangler dev` + curl. The Kodi-side client that talks to it
**is** unit-tested (see `tests/unit/test_device_code_client.py`).

---

## Free-tier limits

Cloudflare Workers' free plan gives you:

- 100,000 requests/day
- KV: 1,000 writes/day, 100,000 reads/day

A single pairing uses a handful of writes and a few dozen poll reads, so for
personal use you will never come close to these limits. If you somehow do,
the Worker simply returns errors until the next daily reset — your TV will
show "Code expired, try again".

## Updating the relay

When a new Kodi-AI version ships an updated `worker.js`, just `git pull` and
re-run `wrangler deploy`. Your KV namespace and URL stay the same, so you do
**not** need to touch Kodi's Relay URL setting again.

## Security notes

- The Worker enforces HTTPS automatically (Cloudflare default).
- It never writes your bot token or OpenRouter key to logs.
- Sessions self-destruct: pending codes expire after 5 minutes; the
  "ready" payload (which briefly holds your secrets) expires after 2 minutes
  and is deleted the instant your TV reads it.
- A per-code submit cap (5 attempts) bounds any guessing of a live code.
- You can rotate your bot token or OpenRouter key any time — they are not
  tied to the relay.
