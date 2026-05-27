# Changelog

All notable changes to Kodi-AI are documented here. The project follows
[Semantic Versioning](https://semver.org/) (with V1 being a personal-use
release).

## [0.3.1] — 2026-05-27

Critical security + correctness fixes from the v0.3.0 post-implementation
review (8 BLOCKERs + 5 HIGH-severity items + 3 cleanup items).

### Security

- **Token redaction in exception logs (B1 / H2 / H4).** Every site that
  catches a `requests.exceptions.RequestException` (or any exception
  near a Telegram / OpenRouter HTTP call) now wraps the message through
  `redactor.redact(repr(e))` before `xbmc.log`. Prevents the Telegram
  bot URL — `api.telegram.org/bot<TOKEN>/...` embedded in HTTPError /
  JSONDecodeError repr — from leaking the bot_token to `kodi.log` and
  `audit.jsonl`.
- **Migration safety (B3).** `_migrate_v0_2_x_bot_token` now only promotes
  a Kodi-side residual bot_token to `secrets.json` if no secret already
  exists. A v0.2.x user with a working secret AND a stale Kodi-settings
  residual no longer risks having the secret overwritten by the stale
  copy.
- **delete_message graceful failure (B8).** If Telegram refuses to delete
  the user's OpenRouter-key message (admin permission gone, message too
  old, network blip), the bot now sends a clear follow-up DM asking the
  user to delete the key from chat history manually. Setup is NOT
  aborted — the key was already saved.
- **Defense-in-depth `openrouter_key` cleanup (R3).** Migration also
  clears any residual `openrouter_key` from Kodi settings (it was a
  Kodi setting in v0.2.x even though read from `secrets.json` at
  runtime). Snapshots/backups of `settings.xml` no longer carry a
  plaintext OpenRouter key.

### Correctness

- **`sk-or-` prefix enforcement (B5).** `setup_callbacks._looks_like_or_key`
  now requires the candidate to start with `sk-or-` before burning an
  HTTP roundtrip on OpenRouter validation. Typos and accidental pastes
  of other tokens get a friendly hint instead.
- **`settings.xml` readonly attribute fix (B6).** `status_display`,
  `bot_username`, and `pairing_command` now use the documented
  `enable="false"` attribute. The undocumented `option="readonly"`
  attribute used in v0.3.0 was not guaranteed to render correctly in
  Kodi v21 (Omega).
- **Bot token hot-swap notice (B2).** `BotHolder.set_token_and_start`
  called with a NEW token after a bot already exists now logs a clear
  warning AND displays a toast asking the user to restart Kodi. The
  in-memory bot reference is replaced (so handlers using `.get()` see
  the new bot for outgoing sends); the running T3 long-poll thread is
  NOT touched and keeps using the old bot until shutdown. Documented
  trade-off — clean hot-swap is deferred to v0.3.2+.
- **Re-entrancy guard (B4).** The settings-changed handler runs under
  `suppress_settings_changed()` so the cascade of setSetting writes
  to derived display fields (`status_display`, `bot_username`,
  `pairing_command`) doesn't trigger self-amplifying onSettingsChanged
  callbacks.
- **`status_display` "no mode" reachability (H1).** The "pick agent
  mode in Telegram" status is now driven by `setup_dm_state` (any
  allowlisted chat in `AWAITING_MODE`), not by reading `settings.mode`
  (which always returns the v1 default "auto" and made the branch
  unreachable).
- **Debounce test coverage (H3).** Added a test that verifies the
  `last_known_bot_token` debounce actually short-circuits a second
  handler invocation with the same token.

### Removed

- `lib/qr.py` (~983 LoC pure-Python Reed-Solomon QR encoder) — was
  unused after the v0.3.0 architecture pivot.
- `tests/unit/test_qr.py` — corresponding tests.

### Docs

- `README.md` — stripped stale references to wizard / QR re-pair flows;
  troubleshooting now points to **Reset bot owner** in Settings →
  Telegram for re-pairing.
- `PRIVACY.md` — `/reset_owner` description updated to reference the
  inline Reset action, not the deleted wizard.
- `HANDOVER.md` — added Section 7 documenting the v0.3.0 → v0.3.1
  pivot and all carry-over decisions.

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
