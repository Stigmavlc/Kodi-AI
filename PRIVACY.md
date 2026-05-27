# Privacy

Kodi-AI is a single-user, single-device add-on. No data is ever sent to a
server controlled by the author. The only outbound network destinations are:

1. **OpenRouter** (`api.openrouter.ai`) — only with redacted log samples
   and prompt context, only when triage marks a batch as `fix-candidate`,
   only up to the user's daily budget cap.
2. **Telegram Bot API** (`api.telegram.org`) — only via the user's own
   bot token, only to/from the chat ID paired during setup.

There is no telemetry, no analytics, no third-party SDK, no crash reporter,
no phone-home.

---

## What is sent off-device

### To OpenRouter

- Triage prompt: redacted log batch + a short system prompt.
- Reasoner prompt: redacted log batch + tool descriptions + tool I/O so far
  in the session + a system prompt.

**Redaction** is performed before any network call by `lib/redactor.py`.
The redactor strips:

- `Authorization: Bearer …` headers and bare bearer tokens
- API keys matching common formats (`sk_…`, `pk_…`, JWTs, etc.)
- Email addresses
- IPv4, IPv6, MAC addresses
- UUIDs
- US SSN-shaped strings
- Credit-card-shaped strings (Luhn-validated)
- File paths under user home that contain a username (the username segment
  is replaced with `<user>`)

Redaction is unit-tested in `tests/unit/test_redactor.py` and
`tests/unit/test_audit_log_redaction.py`.

### To Telegram

- Plain natural-language messages and inline buttons. The Telegram Bot
  API stores messages on Telegram's servers per their
  [Privacy Policy](https://telegram.org/privacy). Only the bot owner
  (you) can see these messages.

### Telegram DM exposure during setup (v0.3.0)

The v0.3.0 inline-settings setup pivot sends the OpenRouter API key
through a Telegram DM during the initial pairing flow (the user pastes
`sk-or-...` to the bot after `/start`). This trades one risk for another:

- **Mitigation 1.** Immediately after validating the key, the bot calls
  the Telegram `deleteMessage` API to scrub the user's message
  containing the plaintext key. This is best-effort — Telegram may
  retain a copy on their servers for some period.
- **Mitigation 2.** The bot never echoes the key back in any reply or
  log line.
- **Residual risk.** Telegram's server-side message history. If your
  Telegram account is compromised, an attacker with retroactive access
  to your chat history could in principle recover the key.
- **User control.** You can rotate your OpenRouter key any time at
  <https://openrouter.ai/keys> — old keys are revocable independently
  of the Telegram chat.

If you would rather not transmit the key through Telegram, you can set
it directly in `secrets.json` (under the Kodi addon userdata directory)
and skip the DM step. See [SECURITY.md](SECURITY.md).

---

## What is stored on-device

State directory (under Kodi's addon userdata, typically
`~/Android/data/.../service.kodi.ai/`):

| File | Contents | Lifetime |
|---|---|---|
| `secrets.json` | Bot token + OpenRouter key + paired chat ID. `chmod 600`. | Until uninstall or `/reset_owner` |
| `audit.jsonl` | Append-only redacted audit of every triage, reasoner step, tool call, outcome. | Until uninstall or manual delete |
| `sessions/<id>.json` | Per-issue session snapshot for crash recovery. | Cleared on session completion |
| `health.json` | Thread liveness + last-event timestamps. | Overwritten in place |
| `budget.json` | Rolling daily spend. | Rolls over at midnight UTC |

Nothing in this directory is transmitted anywhere.

---

## User controls

- **`/reset_owner`** — forgets the paired chat ID. The bot will refuse
  further commands until you use **Reset bot owner** in Settings →
  Telegram and re-pair by sending the displayed `/start <secret>`
  command to the bot.
- **Uninstall** — see [UNINSTALL.md](UNINSTALL.md). Removing the addon
  through Kodi does **not** delete the state directory; you must remove it
  manually if you want a clean wipe.
- **`mode=dry-run`** — disables all write tools; the reasoner can only
  read and report. No fix is ever applied.
- **`budget.daily_usd_cap = 0`** — hard-blocks all OpenRouter calls.

---

## Children

Not designed for or directed at children. Don't run it on a device used by
a child without an adult bot owner.

---

## Contact

For privacy questions or to report a vulnerability, see [SECURITY.md](SECURITY.md).
