"""Kodi-AI service entry point. 4-thread architecture per spec §1.1, §1.2.

Threads:
  Main: KodiAiMonitor (xbmc.Monitor) — waits for abortRequested(), relays
        onSettingsChanged() to T4.
  T2:   LogWatcher (lib/log_watcher.py)  — polls kodi.log, enqueues incidents.
  T3:   TelegramBot.run (lib/telegram/bot.py) — long-poll for user messages.
        Started on-demand by BotHolder when bot_token is first validated.
  T4:   t4_worker_body (this file) — drains work_queue, dispatches to handlers,
        emits heartbeats, handles SettingsChanged (bot_token validation + T3
        start).

Boot ordering (spec §1.1):
  1. T4 starts and runs the boot pass (ensure_dirs, atomic-rename smoke probe,
     redactor canary, health-boot-detect, recovery boot pass, orphan quarantine).
  2. T4 sets startup_complete_event.
  3. T2 + T3 start only AFTER startup_complete_event (gate enforced here).

Shutdown (spec §1.2):
  abort_event.set() -> health.record_clean_shutdown() -> audit shutdown ->
  push sentinel on work_queue -> join T2 (3s) / T3 (15s) / T4 (5s) ->
  log_capture.uninstall().

v0.3.0 settings-inline setup:
  bot_token is typed via the Configure dialog (NOT a wizard). KodiAiMonitor
  posts SettingsChanged to T4 whenever the user OKs the dialog. T4 reads
  the new bot_token from Kodi settings, validates via Telegram getMe,
  copies to secrets.json, clears the plaintext copy in Kodi settings,
  and starts T3 via BotHolder if not already running.

Spec: §1.1, §1.2, §1.14, §2, §3.1, §3.3, §5.7, §7.2, §7.3.
"""
from __future__ import annotations
import os
import sys
import threading
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import xbmc

from lib import state_paths, settings, log_capture, audit_log
from lib import secrets as lib_secrets
from lib import redactor, log_watcher, triage
from lib import reasoner as reasoner_mod
from lib import reasoner_state, pause_sequence
from lib.bot_holder import BotHolder
from lib.setup_monitor import KodiAiMonitor, suppress_settings_changed
from lib.concurrency import (
    abort_event,
    startup_complete_event,
    work_queue,
    paused_sessions,
    paused_sessions_lock,
    MonotonicBudget,
    LogIncident,
    UserMsg,
    ResumeWork,
    SettingsChanged,
)
from lib.llm import client as llm_client, router as llm_router_mod, budget as llm_budget
from lib.telegram import auth as tg_auth, formatters as tg_fmt
import lib.tools  # noqa: F401 — triggers @tool autoload
from lib.tools import registry as tool_registry


# ---- Module-singleton accessors (lazy: deps live in lib.secrets/settings) ----

_router_instance = None
_budget_instance = None


def _get_router():
    global _router_instance
    if _router_instance is None:
        mode = settings.get_string("mode", "auto") or "auto"
        manual_model = settings.get_string("manual_model", "")
        override = settings.get_string("models_override", "")
        _router_instance = llm_router_mod.TaskModelRouter(
            mode=mode if mode in ("auto", "manual") else "auto",
            manual_model=manual_model,
            user_override_json=override,
        )
    return _router_instance


def _get_budget():
    global _budget_instance
    if _budget_instance is None:
        _budget_instance = llm_budget.BudgetGuard(
            per_incident_cap=settings.get_float("per_incident_cap_usd", 0.50),
            daily_cap=settings.get_float("daily_cap_usd", 5.0),
            monthly_cap=settings.get_float("monthly_cap_usd", 30.0),
        )
        try:
            _budget_instance.load()
        except Exception:
            pass
    return _budget_instance


def _get_reasoner(api_key: str):
    return reasoner_mod.Reasoner(
        llm_client=llm_client,
        api_key=api_key,
        router=_get_router(),
        budget=_get_budget(),
        tool_registry=tool_registry,
    )


# ---- T4 handlers (Task 10.3 — inlined per design) ----

def _handle_incident(incident: LogIncident, bot_holder: BotHolder) -> None:
    """LogIncident -> triage -> CRITICAL: reasoner with tools."""
    api_key = lib_secrets.get_secret("openrouter_key")
    if not api_key:
        return
    cluster_text = "\n".join(incident.raw_lines[:10])
    try:
        verdict = triage.classify(
            llm_client,
            api_key=api_key,
            model=_get_router().pick("t0_triage"),
            cluster_text=cluster_text,
        )
    except Exception as e:
        # Defensive — LLM exceptions can carry response bodies that
        # echo the request URL or rejected key. Always redact.
        err = redactor.redact(f"triage failed: {e!r}")
        xbmc.log(f"[service.kodi.ai] {err}", xbmc.LOGWARNING)
        verdict = "IGNORE"
    if verdict != "CRITICAL":
        return
    r = _get_reasoner(api_key)
    session_id = f"sess_{int(time.time() * 1000)}"
    msgs = [
        {
            "role": "user",
            "content": (
                f"Log incident:\n"
                f"Cluster: {incident.cluster_id}\n"
                f"Addon: {incident.likely_addon or 'unknown'}\n"
                f"Severity: {incident.severity_hint}\n"
                f"Lines:\n" + "\n".join(incident.raw_lines[:5])
            ),
        }
    ]
    outcome = r.run_with_tools(
        initial_messages=msgs,
        task_class="t2_reason",
        session_id=session_id,
    )
    _handle_outcome(outcome, bot_holder.get(), session_id, incident.cluster_id)


def _handle_user_msg(msg: UserMsg, bot_holder: BotHolder) -> None:
    """UserMsg -> chat-mode reasoner. Echoes config errors back to user."""
    api_key = lib_secrets.get_secret("openrouter_key")
    bot = bot_holder.get()
    if not api_key:
        if bot is not None:
            try:
                bot.send_message(msg.chat_id, "OpenRouter key not configured.")
            except Exception:
                pass
        return
    r = _get_reasoner(api_key)
    session_id = f"chat_{int(time.time() * 1000)}"
    outcome = r.run_with_tools(
        initial_messages=[{"role": "user", "content": msg.text}],
        task_class="t1_simple",
        session_id=session_id,
    )
    _handle_outcome(outcome, bot, session_id, None, target_chat_id=msg.chat_id)


def _handle_resume_work(rw: ResumeWork, bot_holder: BotHolder) -> None:
    """ResumeWork -> look up paused session (memory then disk) -> reasoner.resume_from."""
    api_key = lib_secrets.get_secret("openrouter_key")
    if not api_key:
        return
    with paused_sessions_lock:
        state = paused_sessions.get(rw.session_id)
    if state is None:
        state = reasoner_state.load(rw.session_id)
    if state is None:
        xbmc.log(
            f"[service.kodi.ai] resume: session {rw.session_id} not found",
            xbmc.LOGWARNING,
        )
        return
    r = _get_reasoner(api_key)
    try:
        b = MonotonicBudget.from_dict(state.budget_blob)
        if b.state.name == "PAUSED":
            b.resume()
    except Exception as e:
        xbmc.log(
            f"[service.kodi.ai] resume budget rehydrate failed: {e}",
            xbmc.LOGWARNING,
        )
    outcome = r.resume_from(
        state=state, user_reply=rw.user_reply, task_class="t2_reason"
    )
    _handle_outcome(outcome, bot_holder.get(), state.session_id, state.cluster_id)


def _handle_outcome(outcome, bot, session_id: str, cluster_id, target_chat_id=None) -> None:
    """Dispatch ReasonerOutcome terminal_reason to user-facing action."""
    chat_ids = [target_chat_id] if target_chat_id is not None else tg_auth.chat_allowlist()

    if outcome.terminal_reason == "needs_user":
        if not chat_ids or bot is None:
            xbmc.log(
                "[service.kodi.ai] needs_user but no Telegram recipient — dropping",
                xbmc.LOGWARNING,
            )
            return
        # Build a fresh MonotonicBudget so pause_and_persist can call .pause() on it.
        # (BudgetGuard is the 3-tier cost guard; MonotonicBudget is the wall-clock
        # session budget passed into pause_sequence per spec §1.7/§1.8.)
        try:
            mono = MonotonicBudget(limit_s=60.0)
            mono.start()
            mono.pause()
            budget_blob = mono.to_dict()
        except Exception:
            mono = MonotonicBudget(limit_s=60.0)
            budget_blob = mono.to_dict()
        state = reasoner_state.SessionState(
            session_id=session_id,
            messages=outcome.messages_so_far,
            tool_history=outcome.tool_history,
            pending_tool={
                "name": outcome.pending_tool,
                "args": outcome.pending_args,
            },
            snapshot_ids=outcome.snapshot_ids,
            terminal_state="paused",
            paused_at=time.time(),
            budget_blob=budget_blob,
            cluster_id=cluster_id,
        )

        def send_telegram() -> bool:
            try:
                kb = {
                    "inline_keyboard": [
                        [
                            {"text": "Yes", "callback_data": f"resume:{session_id}:True"},
                            {"text": "No", "callback_data": f"resume:{session_id}:False"},
                        ]
                    ]
                }
                tool_name = outcome.pending_tool or "unknown"
                tool_args = outcome.pending_args or "{}"
                res = bot.send_message(
                    chat_ids[0],
                    f"<b>Confirm tool:</b> {tg_fmt.escape_html(tool_name)}\n\n"
                    f"<code>{tg_fmt.escape_html(tool_args)}</code>",
                    reply_markup=kb,
                )
                return bool(res.get("ok"))
            except Exception:
                return False

        try:
            pause_sequence.pause_and_persist(
                state=state,
                budget=mono,
                telegram_send_callable=send_telegram,
            )
        except Exception as e:
            xbmc.log(
                f"[service.kodi.ai] pause_sequence failed: {e}", xbmc.LOGERROR
            )
        return

    # complete / max_turns / error / budget_refused / budget_truncated / aborted
    if outcome.final_message and bot is not None:
        for cid in chat_ids:
            try:
                bot.send_message(
                    cid, tg_fmt.truncate(tg_fmt.escape_html(outcome.final_message))
                )
            except Exception:
                pass


# ---- SettingsChanged handler (v0.3.0 inline-setup flow) ----


def _compute_status_display() -> str:
    """Return the right status_display label for the current configuration.

    Decision tree:
      bot_token missing               -> "Not configured"
      bot_token present, no allowlist -> "Bot verified - send /start to @<u>"
      paired, no openrouter_key       -> "Paired - waiting for OpenRouter key"
      paired + key, mid-DM-flow       -> "Paired - pick agent mode in Telegram"
      everything set                  -> "Active - monitoring Kodi logs"

    H1 — Mode-pending branch uses `setup_dm_state` (not Kodi's enum value)
    as the signal. `settings.xml` defaults `mode` to "auto", so reading
    Kodi's setting after install would always return "auto" and the
    branch would be unreachable. The user hasn't actually CONFIRMED a
    mode until they tap the Auto/Manual inline button in Telegram — at
    which point the bot transitions the chat's DM state to DONE.
    Therefore: any allowlisted chat still in AWAITING_MODE means the
    user has paired + provided key but hasn't tapped a mode button.
    """
    has_bot = bool(lib_secrets.get_secret("bot_token"))
    if not has_bot:
        return "Not configured"
    allowlist = tg_auth.chat_allowlist()
    if not allowlist:
        username = settings.get_string("bot_username", "") or ""
        if username and not username.startswith("("):
            return f"Bot verified - send /start to @{username} in Telegram"
        return "Bot verified - open Telegram to pair"
    has_key = bool(lib_secrets.get_secret("openrouter_key"))
    if not has_key:
        return "Paired - waiting for OpenRouter key (check Telegram)"
    # H1 — check setup_dm_state for any allowlisted chat that's still
    # mid-flow. AWAITING_MODE means key validated but mode-button not
    # tapped. If any chat is mid-flow, surface the "pick agent mode"
    # status. Defensive try/except: setup_dm_state read should be cheap
    # but we never want status computation to crash T4.
    try:
        from lib.telegram import setup_dm_state as _dm_state
        for chat_id in allowlist:
            try:
                state = _dm_state.get_state(int(chat_id))
            except (TypeError, ValueError):
                continue
            if state == _dm_state.AWAITING_MODE:
                return "Paired - pick agent mode in Telegram"
    except Exception:
        # Bare except — status computation must never raise.
        pass
    return "Active - monitoring Kodi logs"


def _refresh_status_label() -> None:
    """Recompute + persist status_display. Idempotent and cheap."""
    try:
        new_status = _compute_status_display()
        cur = settings.get_string("status_display", "")
        if cur != new_status:
            settings.set_string("status_display", new_status)
    except Exception as e:
        xbmc.log(
            f"[service.kodi.ai] refresh_status_label failed: {e}",
            xbmc.LOGWARNING,
        )


def _handle_settings_changed(bot_holder: BotHolder, state: dict) -> None:
    """Process a SettingsChanged event.

    `state` is a mutable dict owned by t4_worker_body that persists across
    invocations. Used keys:
      last_known_bot_token (str): most recent validated bot_token, so we
        only re-validate when the user actually changed it.

    Flow:
      1. Invalidate the settings cache.
      2. Read bot_token from Kodi settings.
      3. If bot_token unchanged or empty -> just refresh status_display + return.
      4. If bot_token changed: call getMe -> if valid, copy to secrets, clear
         Kodi settings copy, refresh derived display fields, start T3.
         If invalid: set status to error. Keep user input (so they can fix it).

    B4 — Whole handler runs under suppress_settings_changed() because the
    setSetting calls inside this body (status_display, bot_username,
    pairing_command, clear-bot_token) would otherwise each trigger a
    fresh onSettingsChanged callback and re-enqueue SettingsChanged
    work items in a self-amplifying cascade.
    """
    with suppress_settings_changed():
        _handle_settings_changed_inner(bot_holder, state)


def _handle_settings_changed_inner(bot_holder: BotHolder, state: dict) -> None:
    """B4 helper: actual handler body. Always invoked under the
    suppress_settings_changed() context — see _handle_settings_changed.
    Split out so the suppress contract has a single, easy-to-audit
    entry point."""
    # 1. Cache invalidation — sees fresh values for everything below.
    try:
        settings.invalidate_cache()
    except Exception:
        pass

    # 2. Read bot_token from KODI settings (NOT secrets — the user just
    # typed this into the Configure dialog, it hasn't moved to secrets.json
    # yet). On error / missing, default to "".
    try:
        import xbmcaddon  # imported lazily so unit tests can stub it.
        kodi_bot_token = (
            xbmcaddon.Addon("service.kodi.ai").getSetting("bot_token") or ""
        ).strip()
    except Exception as e:
        # B1 / H4 — always redact exception repr/text before logging in
        # any path that handles bot_token. Even if this particular
        # exception doesn't carry the token, sibling sites do, and a
        # consistent rule is more auditable than per-site judgment.
        err = redactor.redact(f"read bot_token failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGWARNING,
        )
        kodi_bot_token = ""

    last = state.get("last_known_bot_token", "")

    # 3. Token unchanged or empty — just refresh status (other fields may
    # have moved, e.g. allowlist after pairing).
    if not kodi_bot_token or kodi_bot_token == last:
        # If the secret already has the bot_token, no validation needed —
        # state changes elsewhere (pairing, openrouter_key set) just need
        # the derived display refreshed.
        _refresh_status_label()
        return

    # 4. New bot token typed — validate via direct getMe call.
    state["last_known_bot_token"] = kodi_bot_token
    try:
        import requests
        r = requests.get(
            f"https://api.telegram.org/bot{kodi_bot_token}/getMe",
            timeout=10,
        )
        status_code = r.status_code
        try:
            body = r.json()
        except Exception:
            body = {}
    except requests.exceptions.RequestException as e:
        # B1 — RequestException subclasses (HTTPError, JSONDecodeError,
        # InvalidURL, etc.) EMBED THE FULL REQUEST URL in their repr/
        # str(), which here is api.telegram.org/bot<TOKEN>/getMe. Without
        # redaction, the token leaks into kodi.log AND audit_log. The
        # redactor's URL-aware pattern (introduced in v0.2.1) handles
        # this exact case, but only if we actually CALL it.
        err = redactor.redact(f"getMe network error: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGWARNING,
        )
        # Network error — keep user input, advise retry.
        try:
            settings.set_string(
                "status_display",
                "Could not reach Telegram - retry later",
            )
        except Exception:
            pass
        try:
            import xbmcgui
            xbmcgui.Dialog().notification(
                "Kodi-AI", "Telegram unreachable, will retry", time=5000,
            )
        except Exception:
            pass
        return
    except Exception as e:
        err = redactor.redact(f"getMe failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGERROR,
        )
        return

    # HTTP 4xx -> invalid token (most commonly 401).
    if not body.get("ok") or status_code >= 400:
        # H4 — Telegram error response bodies CAN echo the request URL
        # in their `description` field on rare error paths. Redact the
        # body dump before logging.
        body_safe = redactor.redact(repr(body))
        xbmc.log(
            f"[service.kodi.ai] settings_changed: bot token invalid "
            f"(status={status_code}, body={body_safe})",
            xbmc.LOGWARNING,
        )
        try:
            settings.set_string(
                "status_display",
                "Invalid bot token - check it from BotFather",
            )
        except Exception:
            pass
        try:
            import xbmcgui
            xbmcgui.Dialog().notification(
                "Kodi-AI", "Bot token invalid", time=5000,
            )
        except Exception:
            pass
        return

    # Valid! Extract username (used in pairing_command + status).
    username = (body.get("result") or {}).get("username", "") or ""

    # Defensive diagnostic: getMe reporting ok with an empty username is
    # suspicious — a valid bot always has a username. When this happens the
    # downstream status/pairing labels fall back to their generic "pair in
    # Telegram" form, which previously looked like stale state on-device.
    # Log a redacted warning so we can distinguish a real bug from a stale
    # display next time (no token in this message; username is non-secret).
    if not username:
        xbmc.log("[service.kodi.ai] settings_changed: getMe ok but username "
                 "empty - status will show generic 'pair in Telegram'",
                 xbmc.LOGWARNING)

    # Promote bot_token: secrets.json (source of truth) + clear Kodi setting
    # (security hardening — prevents the plaintext token from sitting in
    # Kodi's settings XML where a snapshot/backup might pick it up).
    try:
        lib_secrets.set_secret("bot_token", kodi_bot_token)
    except Exception as e:
        err = redactor.redact(f"set_secret bot_token failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGERROR,
        )
    try:
        import xbmcaddon
        xbmcaddon.Addon("service.kodi.ai").setSetting("bot_token", "")
        # Also invalidate our cache copy so subsequent reads see the empty
        # Kodi value (we deliberately cleared it).
        settings.invalidate_cache()
    except Exception as e:
        err = redactor.redact(f"clear Kodi bot_token failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGWARNING,
        )

    # Save the auto-detected username for display + pairing command.
    if username:
        try:
            settings.set_string("bot_username", username)
        except Exception:
            pass

    # Fresh setup_secret for pairing.
    try:
        secret = tg_auth.generate_setup_secret()
    except Exception as e:
        err = redactor.redact(f"generate_setup_secret failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGERROR,
        )
        secret = ""

    # Update pairing_command label (read-only setting the user sees in the
    # Configure dialog).
    try:
        if username and secret:
            settings.set_string(
                "pairing_command",
                f"/start {secret} to @{username}",
            )
        elif secret:
            settings.set_string("pairing_command", f"/start {secret}")
    except Exception:
        pass

    # Update status.
    try:
        if username:
            settings.set_string(
                "status_display",
                f"Bot verified - send /start to @{username} in Telegram",
            )
        else:
            settings.set_string(
                "status_display", "Bot verified - open Telegram to pair",
            )
    except Exception:
        pass

    # Start T3 long-poll on demand. Per v0.3.0 design + B2 limitation:
    # on subsequent calls with a NEW token the existing T3 keeps using
    # the OLD bot until restart. set_token_and_start surfaces that
    # constraint as a toast.
    try:
        bot_holder.set_token_and_start(kodi_bot_token)
    except Exception as e:
        err = redactor.redact(f"start T3 failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] settings_changed: {err}",
            xbmc.LOGERROR,
        )

    # Toast.
    try:
        import xbmcgui
        toast_text = (
            f"Bot verified - send /start to @{username}"
            if username
            else "Bot verified - pair in Telegram"
        )
        xbmcgui.Dialog().notification("Kodi-AI", toast_text, time=5000)
    except Exception:
        pass


# ---- v0.2.x -> v0.3.0 migration helper ----


def _migrate_v0_2_x_bot_token() -> None:
    """One-shot at boot: if residual plaintext bot_token sits in Kodi
    settings (from v0.2.x where it was a normal setting), move it to
    secrets.json and clear the plaintext copy.

    Safe to call every boot — short-circuits cleanly when nothing to do.

    B3 — Migration MUST NOT overwrite a valid existing secret. v0.2.x
    users who upgraded smoothly may have BOTH a working bot_token in
    secrets.json AND a stale residual copy in Kodi settings.xml. The
    Kodi-side copy is potentially out of date; the secret is the
    source of truth. Only promote when the secret is EMPTY. Always
    clear the plaintext residual either way (defense in depth — a
    plaintext token in settings.xml is a backup/snapshot leak vector).

    R3 — Also clear openrouter_key from Kodi settings as defense in
    depth. v0.2.x had openrouter_key as a Kodi setting (read-from-
    secrets at runtime), so a residual plaintext value may persist.
    """
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon("service.kodi.ai")
        residual = (addon.getSetting("bot_token") or "").strip()
        # R3 — opportunistically clear openrouter_key residual too. We
        # do this whether or not bot_token residual exists, because
        # both settings were promoted to secrets.json in v0.3.0.
        try:
            or_residual = (addon.getSetting("openrouter_key") or "").strip()
            if or_residual:
                addon.setSetting("openrouter_key", "")
                xbmc.log(
                    "[service.kodi.ai] v0.3.0 migration: cleared "
                    "openrouter_key plaintext from Kodi settings",
                    xbmc.LOGINFO,
                )
        except Exception:
            pass
        if not residual:
            return
        # B3 — only promote the Kodi setting if no secret yet exists.
        # If a secret IS already present (different OR same value),
        # we trust the secret as the source of truth and just clear
        # the plaintext residual. NEVER overwrite a non-empty secret.
        secret_existing = lib_secrets.get_secret("bot_token") or ""
        if not secret_existing:
            lib_secrets.set_secret("bot_token", residual)
            xbmc.log(
                "[service.kodi.ai] v0.3.0 migration: moved bot_token to "
                "secrets.json",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log(
                "[service.kodi.ai] v0.3.0 migration: secret bot_token "
                "already present — preserving secret, clearing Kodi "
                "plaintext residual",
                xbmc.LOGINFO,
            )
        # Always clear the plaintext copy.
        addon.setSetting("bot_token", "")
        settings.invalidate_cache()
    except Exception as e:
        # Redact in case the platform mirror echoed any token-bearing
        # path into the exception text.
        err = redactor.redact(f"v0.3.0 migration failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] {err}", xbmc.LOGWARNING,
        )


# ---- T4 worker body ----

HEARTBEAT_INTERVAL_S = 300.0


def t4_worker_body(bot_holder: BotHolder) -> None:
    """T4 main loop: boot pass -> work_queue drain + heartbeat."""
    # Boot pass: each step is wrapped — a single failure must not kill T4.
    try:
        state_paths.ensure_dirs()
    except Exception as e:
        xbmc.log(f"[service.kodi.ai] ensure_dirs failed: {e}", xbmc.LOGERROR)
    try:
        if not state_paths.smoke_probe_atomic_rename():
            xbmc.log(
                "[service.kodi.ai] atomic-rename smoke probe FAILED",
                xbmc.LOGWARNING,
            )
    except Exception as e:
        xbmc.log(f"[service.kodi.ai] atomic-rename probe error: {e}", xbmc.LOGWARNING)
    try:
        ok_c, leaked = redactor.canary_self_test()
        if not ok_c:
            xbmc.log(
                f"[service.kodi.ai] REDACTOR CANARY FAILED — LLM disabled. leaked={leaked}",
                xbmc.LOGERROR,
            )
    except Exception as e:
        xbmc.log(f"[service.kodi.ai] canary error: {e}", xbmc.LOGWARNING)

    # Tool registry probe (Task 11.1): if autoload silently skipped modules
    # (e.g. an xbmc-dependent import failed at startup), the agent has a
    # crippled toolbox. Surface in Kodi log so the user can see it via
    # /diagnostics or kodi.log review.
    try:
        _tool_count = len(tool_registry.registry)
        if _tool_count < 5:
            xbmc.log(
                f"[service.kodi.ai] SMOKE: tool registry has only "
                f"{_tool_count} tools — autoload may have failed",
                xbmc.LOGWARNING,
            )
        else:
            xbmc.log(
                f"[service.kodi.ai] SMOKE: tool registry has "
                f"{_tool_count} tools",
                xbmc.LOGINFO,
            )
    except Exception as e:
        xbmc.log(
            f"[service.kodi.ai] SMOKE: tool registry probe FAILED: {e}",
            xbmc.LOGERROR,
        )

    # Audit log size warning (Task 11.1): audit_log writes are append-only
    # so size grows monotonically. Emit a warning past 10 MB so the user
    # can trigger rotation manually until automatic rotation lands.
    try:
        _audit_path = state_paths.profile_path("audit/audit.jsonl")
        if os.path.exists(_audit_path):
            _audit_size = os.path.getsize(_audit_path)
            if _audit_size > 10 * 1024 * 1024:
                xbmc.log(
                    f"[service.kodi.ai] SMOKE: audit log is {_audit_size} "
                    f"bytes — may need rotation",
                    xbmc.LOGWARNING,
                )
    except Exception:
        pass

    # health + recovery: these modules may not yet exist (Phase 11/12 tasks).
    # Wrap each so missing modules don't kill boot.
    try:
        from lib import health  # type: ignore
        if hasattr(health, "boot_detect_and_update_crash_free_since"):
            health.boot_detect_and_update_crash_free_since()
    except Exception:
        pass
    try:
        from lib import recovery  # type: ignore
        if hasattr(recovery, "boot_recovery_sessions"):
            recovery.boot_recovery_sessions()
        if hasattr(recovery, "quarantine_orphan_snapshots"):
            recovery.quarantine_orphan_snapshots()
    except Exception:
        pass

    # v0.2.x -> v0.3.0 migration (one-shot if applicable).
    _migrate_v0_2_x_bot_token()

    # If a bot_token already exists in secrets (already-paired user, or
    # post-migration), start T3 right now.
    try:
        existing_token = lib_secrets.get_secret("bot_token") or ""
        if existing_token:
            bot_holder.set_token_and_start(existing_token)
    except Exception as e:
        xbmc.log(
            f"[service.kodi.ai] boot T3 start failed: {e}", xbmc.LOGERROR,
        )

    # Set initial status_display based on current state.
    _refresh_status_label()

    # First-launch guidance: if neither OpenRouter key nor bot token is set,
    # show a passive toast so the user knows setup is pending. NEVER auto-
    # opens the wizard (that would be intrusive mid-playback) — just a 5s
    # toast in the corner. Shown once per Kodi boot until setup completes.
    try:
        _has_key = bool(lib_secrets.get_secret("openrouter_key"))
        _has_bot = bool(lib_secrets.get_secret("bot_token"))
        if not (_has_key and _has_bot):
            import xbmcgui
            _icon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "icon.png"
            )
            xbmcgui.Dialog().notification(
                "Kodi-AI",
                "Setup needed - open Configure to begin",
                icon=_icon_path if os.path.exists(_icon_path) else "",
                time=6000,
                sound=False,
            )
    except Exception as e:
        xbmc.log(f"[service.kodi.ai] first-launch toast failed: {e}",
                 xbmc.LOGWARNING)

    startup_complete_event.set()
    xbmc.log("[service.kodi.ai] startup complete", xbmc.LOGINFO)

    # Persistent state for SettingsChanged debouncing.
    # last_known_bot_token: seeded with whatever's in secrets so a residual
    # value across restart doesn't trigger spurious revalidation.
    settings_state: dict = {
        "last_known_bot_token": lib_secrets.get_secret("bot_token") or "",
    }

    last_heartbeat = time.monotonic()
    from queue import Empty
    while not abort_event.is_set():
        try:
            try:
                item = work_queue.get(timeout=1.0)
            except Empty:
                item = None
            if item is not None:
                _, _, payload = item
                if payload is None:
                    # Shutdown sentinel.
                    continue
                try:
                    if isinstance(payload, LogIncident):
                        _handle_incident(payload, bot_holder)
                    elif isinstance(payload, UserMsg):
                        _handle_user_msg(payload, bot_holder)
                    elif isinstance(payload, ResumeWork):
                        _handle_resume_work(payload, bot_holder)
                    elif isinstance(payload, SettingsChanged):
                        _handle_settings_changed(bot_holder, settings_state)
                    else:
                        xbmc.log(
                            f"[service.kodi.ai] unknown payload type: "
                            f"{type(payload).__name__}",
                            xbmc.LOGWARNING,
                        )
                except Exception as e:
                    xbmc.log(
                        f"[service.kodi.ai] handler exception: {e}", xbmc.LOGERROR
                    )
        except Exception as e:
            xbmc.log(f"[service.kodi.ai] T4 loop error: {e}", xbmc.LOGERROR)
        if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            try:
                from lib import health  # type: ignore
                if hasattr(health, "heartbeat"):
                    health.heartbeat()
            except Exception:
                pass
            last_heartbeat = time.monotonic()


def main() -> None:
    """Service entry point. Stays in Monitor loop until Kodi requests abort."""
    try:
        log_capture.install(verbose=settings.get_bool("diagnostic_logging", False))
    except Exception:
        pass
    try:
        audit_log.write("startup", details={"version": "0.3.2"})
    except Exception:
        pass

    # BotHolder is the single mutable handle T4 / handlers consult.
    bot_holder = BotHolder()

    # T4 first: must run boot pass + set startup_complete_event before T2/T3.
    t4 = threading.Thread(
        target=t4_worker_body, args=(bot_holder,), name="T4_Worker", daemon=False
    )
    t4.start()
    startup_complete_event.wait(timeout=60)

    # T2: log watcher.
    watcher = log_watcher.LogWatcher(
        poll_active_ms=settings.get_int("t2_poll_active_ms", 750),
        poll_idle_ms=settings.get_int("t2_poll_idle_ms", 2500),
    )
    t2 = threading.Thread(target=watcher.run, name="T2_LogPoll", daemon=False)
    t2.start()

    # T3 starts on-demand via BotHolder (either right now during boot if
    # bot_token already exists in secrets, or later when the user types
    # one into Kodi settings -> SettingsChanged -> _handle_settings_changed).
    # The boot-time start happens inside t4_worker_body BEFORE the work
    # loop, so by the time main() resumes here, T3 may already be running
    # (no work needed) or will start later (no work needed).

    xbmc.log(
        "[service.kodi.ai] all threads running; entering Monitor loop",
        xbmc.LOGINFO,
    )
    monitor = KodiAiMonitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(1.0):
            break

    # Shutdown protocol.
    xbmc.log("[service.kodi.ai] shutdown initiated", xbmc.LOGINFO)
    abort_event.set()
    try:
        from lib import health  # type: ignore
        if hasattr(health, "record_clean_shutdown"):
            health.record_clean_shutdown()
    except Exception:
        pass
    try:
        audit_log.write("shutdown")
    except Exception:
        pass
    try:
        # Push a sentinel so T4's blocking get() returns promptly.
        work_queue.put_nowait((100, 99999, None))
    except Exception:
        pass

    if t2 is not None:
        t2.join(timeout=3)
    t3 = bot_holder.t3_thread()
    if t3 is not None:
        t3.join(timeout=15)
    t4.join(timeout=5)

    try:
        log_capture.uninstall()
    except Exception:
        pass


if __name__ == "__main__":
    main()
