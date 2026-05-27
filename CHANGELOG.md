# Changelog

All notable changes to Kodi-AI are documented here. The project follows
[Semantic Versioning](https://semver.org/) (with V1 being a personal-use
release).

## [0.3.0] — 2026-05-27

Complete setup-UX rewrite. The phone-driven WindowXMLDialog + local HTTP
server from v0.2.x had fatal browser-compat issues (Brave's HTTPS-Only
mode, Firefox-Android cert warnings that can't be bypassed, mDNS blocked
in privacy-hardened browsers). v0.3.0 replaces it entirely.

### Changed

- **Inline-settings setup.** All configuration lives in Kodi's standard
  Configure dialog (gear icon → Settings - Kodi-AI). The Telegram tab is
  now the primary setup area with inline step-by-step instructions:
  step 1 (paste bot token from @BotFather), step 2 (send the displayed
  `/start <secret>` command in Telegram), step 3 (the bot DMs you for
  the OpenRouter key + agent mode). A "Tip" section recommends Kore /
  Yatse remote-paste apps to avoid TV keyboard typing.
- **Bot-driven DM setup.** After pairing, the bot asks for the OpenRouter
  API key via DM, validates it via a 1-token ping, then asks for agent
  mode via inline buttons (Auto / Manual). The user's key message is
  deleted immediately after validation so the plaintext key doesn't
  linger in chat history.
- **On-demand T3 startup.** The Telegram long-poll thread now starts
  the moment a valid `bot_token` is typed into Configure, rather than
  only at boot. `BotHolder` (lib/bot_holder.py) owns the mutable bot
  reference.
- **`KodiAiMonitor`** subclass of xbmc.Monitor relays `onSettingsChanged`
  to T4 as a `SettingsChanged` work item, which triggers bot-token
  validation + T3 startup + status_display refresh.
- **`bot_token` security hardening.** After validation, the token is
  copied to `secrets.json` and the plaintext Kodi-settings copy is
  cleared (avoids leaking via backups/snapshots of settings XML).
- **default.py simplified.** Old `setup_via_phone`, `setup_wizard`,
  `show_secret` actions removed. Only `show_status_panel` + `reset_bot`
  remain.

### Removed

- `lib/setup_server.py` (local HTTPS server).
- `lib/setup_window.py` (WindowXMLDialog).
- `lib/setup_ip.py` (LAN-IP probe).
- `resources/skins/Default/720p/Setup.xml`.
- `resources/web/setup.html`.
- `resources/media/setup_bg.png`, `btn_focus.png`, `btn_nofocus.png`,
  `step_pending.png`, `step_done.png`.
- The phone-pairing wizard's auto-launch in default.py.

### Migration from v0.2.x

If you previously had a working v0.2.x install:

- Your `secrets.json` (bot_token + openrouter_key) is unchanged. The
  service continues to use them.
- If your `bot_token` was still in Kodi's settings.xml (e.g. unusual
  install path), the service auto-migrates it to `secrets.json` on the
  first boot of 0.3.0 and clears the plaintext copy.
- Re-pairing is NOT required if `chat_allowlist.json` already exists.
- The new Configure dialog's Telegram tab will show "✓ Active —
  monitoring Kodi logs" if everything carries over.

### Added (tests + infra)

- `lib/setup_monitor.KodiAiMonitor` — xbmc.Monitor subclass.
- `lib/bot_holder.BotHolder` — on-demand T3 thread management.
- `lib/concurrency.SettingsChanged` — new work-queue item type.
- `lib/telegram/setup_dm_state` — schema-versioned per-chat DM state.
- `lib/telegram/setup_callbacks` — DM handlers for OR key + mode.
- 36 new unit tests across setup_monitor, settings_changed_handler,
  setup_dm_state, telegram_dm_setup. Total suite: 327 → 363 → final.

## [0.1.0] — 2026-05-27

Initial V1 release. Targeting Kodi 21 (Omega) on Nvidia Shield Pro / Android TV.

### Added

- **`xbmc.service` add-on** that runs in the background and tails Kodi's log.
- **Pre-filter + sentinels** so most log lines never reach an LLM.
- **Triage stage** using a cheap LLM (`gpt-4o-mini` class) to classify each
  batch as `ignore` / `info` / `fix-candidate`.
- **Reasoner stage** — tool-using LLM agent (OpenRouter) bounded by step,
  budget, and wall-clock caps. Tool set: settings reader, addon restarter,
  userdata file writer, Telegram-ask, verifier.
- **Verifier** — confirms fix outcome via silence window or explicit log
  signal.
- **Telegram bot** — long-poll only (no webhooks). Owner-only pairing flow
  with QR + `/start` deep link. Commands: `/status`, `/recent`, `/pause`,
  `/resume`, `/mode`, `/budget`, `/reset_owner`, `/help`. Inline-button
  flows for `ask` mode.
- **Redactor** — strips Authorization headers, Bearer tokens, API keys,
  emails, IPs, MACs, UUIDs, SSNs, and credit-card patterns from any text
  before it leaves the device.
- **Budget tracking** — daily USD cap with hard kill switch, per-model
  cost accounting, rolling state in `budget.json`.
- **Audit log** — append-only `audit.jsonl` of every triage, reasoner
  step, tool call, and outcome.
- **Health snapshot** — `health.json` with thread liveness, last-event
  timestamps, error counts.
- **Recovery** — graceful resume of in-flight reasoner sessions across
  Kodi restarts.
- **Settings UI** — full settings.xml with the wizard flow on first run.
- **Distribution** — `tools/build_repo.py` produces a Kodi-compatible
  addon repository; GitHub Pages workflow publishes it on every push to
  `main`.

### Known limitations (intentional for V1)

- Single user, single device.
- Telegram long-poll only — no webhook server.
- No multi-step plan editing UI; reasoner plan is opaque to the user
  beyond what the audit log shows.
- No A/B routing of models; both triage and reasoner models are pinned.
- Acceptance tests are manual (run on the Shield Pro), not in CI.
