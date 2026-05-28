# Kodi-AI

AI-assisted Kodi diagnostics + auto-fix, surfaced over Telegram.

Kodi-AI is a `xbmc.service` add-on for Kodi 21 (Omega) on Android TV (Nvidia
Shield Pro). It quietly watches Kodi's log, classifies issues with a cheap
LLM, runs a tool-using LLM agent (via OpenRouter) to try a fix when one is
warranted, and reports back through a Telegram bot you control.

V1 is intentionally personal — single-user, single-device, no webhooks, no
cloud state. Long-poll Telegram only. All session data lives on the device.

---

## Install

### Method 1: Repository (recommended)

1. On Android TV, enable **Settings → System → Add-ons → Unknown sources**.
2. Download the repository zip on any device:
   <https://stigmavlc.github.io/Kodi-AI/repository.kodi-ai.stigmavlc-0.1.0.zip>
3. Transfer the zip to your Shield Pro (USB stick or
   `/storage/emulated/0/Download/`).
4. In Kodi: **Add-ons → Install from zip file →** select the repository zip.
5. **Add-ons → Install from repository → Kodi-AI Repository → Services →
   Kodi-AI → Install.**
6. Updates ship through the repository on every push to `main` of this
   GitHub repo.

### Method 2: Direct zip

1. Download the addon zip:
   <https://stigmavlc.github.io/Kodi-AI/service.kodi.ai-0.1.0.zip>
2. Copy it to a USB stick or to `/storage/emulated/0/Download/` on the Shield.
3. In Kodi: **Add-ons → Install from zip file →** select the addon zip.

### Build locally

```bash
git clone https://github.com/Stigmavlc/Kodi-AI.git
cd Kodi-AI
python tools/build_repo.py
# Produces dist/service.kodi.ai-0.1.0.zip and dist/repository.kodi-ai-*.zip
```

---

## First-run setup

Setup happens from your phone — no typing long tokens on a TV remote.

### One-time: deploy your relay

The phone setup talks to a tiny **Cloudflare Worker that you deploy on your
own free Cloudflare account**. It only ever brokers your secrets transiently
(under 2 minutes, never logged) — it is your relay, no third party involved.

Follow [cloudflare/DEPLOY.md](cloudflare/DEPLOY.md) once (~5 minutes). At the
end you paste your Worker URL (`https://kodi-ai-relay.<you>.workers.dev`) into
Kodi: **Add-ons → Kodi-AI → Configure → Advanced → Relay URL**.

### Set up via phone

1. **Open Configure → Telegram → "Set up via phone".**
2. Your TV shows a short **code** and the relay URL.
3. On your phone, open that URL, type the code, then fill the form:
   - **Bot token** — in Telegram, message
     [@BotFather](https://t.me/BotFather), send `/newbot`, follow the prompts,
     copy the token, and tap **Validate** (it confirms your bot's @username).
   - **OpenRouter key** — from <https://openrouter.ai/keys> (~$5 of credit
     lasts a long time). Tap **Validate**.
   - **Mode** — Auto (recommended) or Manual.
   - Tap **Send to TV**.
4. **Confirm on your TV.** Kodi shows the bot @username it received and asks
   "Is this YOUR bot?". Confirm.
5. **Finish in Telegram.** Open your bot and tap **Start** (or the
   "Open Telegram to finish pairing" button on your phone, *after* the TV
   shows it's ready).

After setup, the **Status** label in Configure → Telegram shows the bot is
verified and then **Active** once monitoring begins. You're done.

### No phone? Manual fallback

If you'd rather not use the relay, choose **Configure → Telegram → "Manual
setup"** instead. Type the bot token on the TV; Kodi validates it and shows
the `/start <secret>` command to send to your bot, which then DMs you for the
OpenRouter key + mode.

Settings (budget caps, redaction allowlist, etc.) live in the same Configure
dialog under their own tabs.

---

## Daily use

All interaction happens through your Telegram bot. Commands:

| Command | Effect |
|---|---|
| `/status` | Current Kodi state, active session (if any), today's spend |
| `/recent` | Last 10 issues + outcomes |
| `/pause [minutes]` | Pause monitoring for N minutes (default 60) |
| `/resume` | Resume monitoring |
| `/mode auto|ask|dry-run` | Switch mode |
| `/budget` | Show today's spend vs cap |
| `/reset_owner` | Forget the paired chat (used to re-pair) |
| `/help` | Reminder of all commands |

When the add-on detects an issue, you get a notification with a short
summary and (in `ask` mode) inline buttons to **Apply** / **Skip** /
**Pause**.

---

## How it works

1. **Log watcher** tails `kodi.log` in a background thread, batches lines,
   and pre-filters with cheap regex sentinels so most lines never reach an
   LLM.
2. **Triage** sends a redacted sample to a cheap LLM model (`gpt-4o-mini`
   class) to classify each batch as `ignore`, `info`, or `fix-candidate`.
3. **Reasoner** runs only on fix-candidates: a tool-using agent (OpenRouter)
   with a small fixed toolbox (read add-on settings, restart add-on, write
   userdata file, ask user via Telegram, verify outcome). The reasoner is
   bounded by step cap, budget cap, and a wall-clock timeout.
4. **Verifier** confirms whether the fix worked (silence in logs for N
   minutes, or explicit log signal).
5. **Telegram bot** is long-poll only (no webhooks, no public endpoint).
   Notifications, prompts, and replies all flow through your owned chat.

Everything is single-threaded inside each component except the four
top-level orchestrator threads (log capture, triage, reasoner queue,
telegram poller).

---

## Configuration

Most users only touch Step 1 in the Telegram tab of Configure — the rest
happens in your Telegram chat. The full setting set lives in
`service.kodi.ai/resources/settings.xml` and is editable in Kodi via the
add-on Configure dialog. Highlights:

- `telegram.bot_token` — bot token from BotFather.
- `llm.openrouter_api_key` — OpenRouter key.
- `llm.triage_model` / `llm.reasoner_model` — pinned model IDs.
- `mode` — `auto` / `ask` / `dry-run`.
- `budget.daily_usd_cap` — kill switch for spend.
- `safety.allowed_tools` — comma list (advanced, leave default).
- `paths.state_dir` — defaults to add-on userdata.

State directory layout (on-device):

```
~/Android/.../service.kodi.ai/
├── secrets.json       # bot token + API key (chmod 600)
├── audit.jsonl        # redacted append-only audit log
├── sessions/          # per-issue session snapshots
├── health.json        # current health snapshot
└── budget.json        # rolling daily spend
```

---

## Privacy & security

See [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md). The short
version:

- Log lines are **redacted** before any network call (Authorization,
  Bearer, API keys, emails, IPs, MACs, UUIDs, SSNs, credit-card patterns).
- All Telegram traffic is to your own bot only.
- All local state stays on the device. No telemetry, no phone-home.
- `/reset_owner` wipes the paired chat ID.

---

## Troubleshooting

1. **Add-on doesn't start** — open Kodi log (`kodi.log`), look for `[Kodi-AI]`
   prefix. Most start-up failures are a missing API key.
2. **No Telegram replies** — confirm long-poll thread is alive in
   `/status`. If the network on the Shield is flaky, the bot retries with
   exponential backoff.
3. **"Owner not paired"** — use **Reset bot owner** in Settings →
   Telegram, then send `/start <secret>` to the bot again. The pairing
   command is shown in the Configure dialog after the bot token is
   validated.
4. **Hit daily budget** — `/budget` shows current spend. Raise
   `budget.daily_usd_cap` or wait until midnight UTC.
5. **Reasoner keeps timing out** — check `health.json`; the wall-clock cap
   is intentional. Increase `reasoner.timeout_s` cautiously.
6. **Triage seems noisy** — tune the sentinel regexes in `lib/prefilter.py`
   or raise the triage threshold.
7. **No log file found** — confirm `paths.kodi_log` resolves; on Shield Pro
   the default is `~/Android/.../kodi/temp/kodi.log`.
8. **Crash on Kodi shutdown** — verify the Monitor abort path; the service
   exits in <2s on `xbmc.Monitor().waitForAbort()`.
9. **Repository updates not arriving** — Kodi caches addon repos. Force
   refresh via **Add-ons → Install from repository → Kodi-AI Repository →
   Check for updates**.

For full removal, see [UNINSTALL.md](UNINSTALL.md).

---

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

- The Kodi project (XBMC Foundation).
- Telegram Bot API.
- OpenRouter for unified LLM routing.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
