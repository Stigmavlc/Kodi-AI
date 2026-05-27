# Security

Kodi-AI is a personal-use V1 add-on. It is **not** hardened for multi-user
or enterprise deployment. This document records the threat model, the
defenses in place, and how to report security issues.

---

## Threat model (V1)

### In scope

1. **Leakage of secrets** (bot token, API key, paired chat ID) via:
   - logs sent to OpenRouter
   - audit log
   - addon repository zip
   - Telegram messages
2. **Leakage of personally identifying info** in log lines sent to
   OpenRouter (IPs, MACs, file paths, emails).
3. **Unauthorized control of the bot** — someone other than the owner
   triggering tool calls.
4. **Runaway spend** — bug or attacker driving OpenRouter cost up.
5. **Reasoner doing the wrong thing** — tool call that breaks Kodi.

### Out of scope (V1)

- Compromised Android TV root / system-level access.
- Compromise of Telegram's or OpenRouter's infrastructure.
- Physical access to the device.
- Multi-user environments.

---

## Defenses

| Threat | Defense |
|---|---|
| Secret leakage in logs | `lib/redactor.py` strips Authorization, Bearer, API-key, email, IP, MAC, UUID, SSN, CC patterns before any network call. Verified by `tests/unit/test_redactor.py`. |
| Secrets on disk | `secrets.json` written with `os.chmod(0o600)`; only readable by the addon process user. |
| Audit log leakage | Audit log entries go through the same redactor (`tests/unit/test_audit_log_redaction.py`). |
| Repo zip leakage | `tools/build_repo.py` skips `__pycache__`, `.pyc`, tests, and dotfiles. State directory is outside the addon dir, so it can never be zipped accidentally. |
| Unauthorized bot control | Pairing requires a one-shot code shown only in the Kodi UI; only the first chat to submit a valid code becomes owner. All later commands check chat-id == owner. `/reset_owner` is the only way to re-pair, and it requires already being owner. |
| Runaway spend | Hard daily USD cap (`budget.daily_usd_cap`), per-call token cap, step cap on reasoner sessions, wall-clock timeout. Budget state is checked before every OpenRouter call. |
| Bad reasoner action | Allowlist of tools (`safety.allowed_tools`). Write tools require `mode != dry-run`. `ask` mode requires Telegram confirmation per fix. Verifier checks outcome and rolls back the session record if no signal. |

---

## Reporting a vulnerability

Email **ivanaguilarmari@gmail.com** with the subject `Kodi-AI security:
<short summary>`.

Please **do not** open a public GitHub issue for security problems.
Include:

- A description of the issue.
- A reproducible test case if possible.
- Your assessment of impact.

I'll acknowledge within 7 days and fix in the next release.

---

## Cryptography

Kodi-AI does not roll its own crypto. The only places crypto matters:

- HTTPS to Telegram / OpenRouter (provided by `requests` + system trust
  store on Android).
- File permissions on `secrets.json` (`chmod 600`).

There is no encryption at rest beyond filesystem permissions; the threat
model assumes the device is trusted.
