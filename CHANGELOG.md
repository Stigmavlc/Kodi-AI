# Changelog

All notable changes to Kodi-AI are documented here. The project follows
[Semantic Versioning](https://semver.org/) (with V1 being a personal-use
release).

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
