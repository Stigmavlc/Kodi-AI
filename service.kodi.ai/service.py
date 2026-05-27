"""Kodi-AI service entry point. 4-thread architecture per spec §1.1, §1.2.

Threads:
  Main: Kodi's xbmc.Monitor — waits for abortRequested(), then signals shutdown.
  T2:   LogWatcher (lib/log_watcher.py)  — polls kodi.log, enqueues incidents.
  T3:   TelegramBot.run (lib/telegram/bot.py) — long-poll for user messages.
  T4:   t4_worker_body (this file) — drains work_queue, dispatches to handlers,
        emits heartbeats.

Boot ordering (spec §1.1):
  1. T4 starts and runs the boot pass (ensure_dirs, atomic-rename smoke probe,
     redactor canary, health-boot-detect, recovery boot pass, orphan quarantine).
  2. T4 sets startup_complete_event.
  3. T2 + T3 start only AFTER startup_complete_event (gate enforced here).

Shutdown (spec §1.2):
  abort_event.set() → health.record_clean_shutdown() → audit shutdown →
  push sentinel on work_queue → join T2 (3s) / T3 (15s) / T4 (5s) →
  log_capture.uninstall().

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
)
from lib.llm import client as llm_client, router as llm_router_mod, budget as llm_budget
from lib.telegram import bot as telegram_bot_mod, auth as tg_auth, formatters as tg_fmt
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

def _handle_incident(incident: LogIncident, bot) -> None:
    """LogIncident → triage → CRITICAL: reasoner with tools."""
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
        xbmc.log(f"[service.kodi.ai] triage failed: {e}", xbmc.LOGWARNING)
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
    _handle_outcome(outcome, bot, session_id, incident.cluster_id)


def _handle_user_msg(msg: UserMsg, bot) -> None:
    """UserMsg → chat-mode reasoner. Echoes config errors back to user."""
    api_key = lib_secrets.get_secret("openrouter_key")
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


def _handle_resume_work(rw: ResumeWork, bot) -> None:
    """ResumeWork → look up paused session (memory then disk) → reasoner.resume_from."""
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
    _handle_outcome(outcome, bot, state.session_id, state.cluster_id)


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


# ---- T4 worker body ----

HEARTBEAT_INTERVAL_S = 300.0


def t4_worker_body(bot) -> None:
    """T4 main loop: boot pass → work_queue drain + heartbeat."""
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

    startup_complete_event.set()
    xbmc.log("[service.kodi.ai] startup complete", xbmc.LOGINFO)

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
                        _handle_incident(payload, bot)
                    elif isinstance(payload, UserMsg):
                        _handle_user_msg(payload, bot)
                    elif isinstance(payload, ResumeWork):
                        _handle_resume_work(payload, bot)
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
        audit_log.write("startup", details={"version": "0.1.0"})
    except Exception:
        pass

    bot_token = lib_secrets.get_secret("bot_token") or ""
    bot = telegram_bot_mod.TelegramBot(bot_token) if bot_token else None

    # T4 first: must run boot pass + set startup_complete_event before T2/T3.
    t4 = threading.Thread(
        target=t4_worker_body, args=(bot,), name="T4_Worker", daemon=False
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

    # T3: Telegram bot (only if token configured).
    t3 = None
    if bot is not None:
        t3 = threading.Thread(target=bot.run, name="T3_TGPoll", daemon=False)
        t3.start()

    xbmc.log(
        "[service.kodi.ai] all threads running; entering Monitor loop",
        xbmc.LOGINFO,
    )
    monitor = xbmc.Monitor()
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
    if t3 is not None:
        t3.join(timeout=15)
    t4.join(timeout=5)

    try:
        log_capture.uninstall()
    except Exception:
        pass


if __name__ == "__main__":
    main()
