"""Reasoner: LLM tool-use agent loop. T4-owned single-threaded.

Skeleton in 5.3: simple non-tool path (one LLM call → final_message).
Task 5.4: streaming tool loop with mid-stream budget check + tool_history.

Spec: §1.6, §1.7, §1.10, §3.1, §3.3, §5.5, §1.4 (tool-history-match).
"""
from __future__ import annotations
import json
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasonerOutcome:
    final_message: str
    tool_calls_made: int = 0
    terminal_reason: str = "complete"
    # complete | budget_refused | budget_truncated | needs_user | aborted | error | max_turns
    notes: str = ""
    cost_usd: float = 0.0
    snapshot_ids: list[str] = field(default_factory=list)
    tool_history: list[dict] = field(default_factory=list)
    # Task 5.5: pause/resume state carried out on terminal_reason='needs_user'.
    # service.py serializes these into SessionState for telegram_ask + budget.pause.
    pending_tool: str | None = None
    pending_args: str | None = None
    messages_so_far: list[dict] = field(default_factory=list)


class Reasoner:
    def __init__(
        self,
        *,
        llm_client,
        api_key: str,
        router,
        budget,
        tool_registry: dict | None = None,
    ):
        self.llm = llm_client
        self.api_key = api_key
        self.router = router
        self.budget = budget
        self.tool_registry = tool_registry or {}

    def _estimate_cost(self, model: str, messages: list[dict], max_tokens: int) -> float:
        price = self.router.price_per_mtok(model) or (1.0, 5.0)
        in_p, out_p = price
        approx_in_tokens = sum(len(m.get("content") or "") for m in messages) / 4
        return (approx_in_tokens * in_p + max_tokens * out_p) / 1_000_000

    def _persist_budget(self) -> None:
        """Flush the budget counters to disk after a real spend was recorded.

        B1 fix (v0.4.7): record_actual() only mutates the in-memory counters;
        without this call budget_counters.json is never written, so /budget and
        /status (which build a fresh BudgetGuard + .load()) report $0.00 and the
        caps/spend reset on every Kodi restart. persist() is atomic (state_paths
        .atomic_write), so a torn write can't corrupt the counters.

        A persist failure (disk full, FS error) MUST NOT crash the reasoner —
        the run already produced its result and the in-memory guard still
        enforces caps for the rest of this session. We log a redacted warning
        and continue. xbmc is imported lazily so this module stays unit-testable
        without the Kodi runtime (and the log call is best-effort).
        """
        persist = getattr(self.budget, "persist", None)
        if not callable(persist):
            return
        try:
            persist()
        except Exception as e:
            try:
                import xbmc
                from . import redactor
                xbmc.log(
                    f"[service.kodi.ai] {redactor.redact(f'budget persist failed: {e!r}')}",
                    xbmc.LOGWARNING,
                )
            except Exception:
                pass

    def _tool_schemas(self, allowed_tools: set[str] | None = None) -> list[dict]:
        """Build OpenAI tool-use function schemas for the registered tools.

        Each @tool-decorated fn carries .tool_name / .description / .tool_schema
        (see lib/tools/__init__.py). When `allowed_tools` is provided, only tools
        whose name is in that set are exposed — this is how the chat path
        restricts the catalog (criterion E) while the incident path passes the
        full set (allowed_tools=None → expose everything).

        Back-compat: a tool object that exposes a schema_dict() callable (older
        shape) is honored too. Tools missing both shapes are skipped.
        """
        out: list[dict] = []
        for fn in self.tool_registry.values():
            name = getattr(fn, "tool_name", None)
            if allowed_tools is not None and name not in allowed_tools:
                continue
            schema_dict = getattr(fn, "schema_dict", None)
            if callable(schema_dict):
                try:
                    out.append(schema_dict())
                    continue
                except Exception:
                    pass
            if name and getattr(fn, "tool_schema", None) is not None:
                out.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": getattr(fn, "description", ""),
                        "parameters": fn.tool_schema,
                    },
                })
        return out

    @staticmethod
    def _needs_confirmation(tool_obj, args_json: str) -> bool:
        """Confirm-gate predicate (v0.6.0 Part 2, criterion A).

        Returns True when the tool must be confirmed by the user BEFORE it runs,
        per the EXISTING tool_routing_decision contract (tier=="confirm" OR
        disruptive(args) is truthy).

        MagicMock-safety: real @tool functions always carry a string .tier
        ("immediate"|"confirm"). Test doubles (MagicMock) return a MagicMock for
        any unset attribute — that is NOT a real routing signal, so we only
        consult tool_routing_decision when .tier is an actual str. When .tier
        is not a real string (mock/absent), we return False here and rely on the
        legacy post-execution markers (requires_user_confirmation / NEEDS_USER),
        which keeps every pre-0.6.0 test (and the ask_user path) unregressed.
        """
        if tool_obj is None:
            return False
        # ask_user (and any tool that opts into the legacy "ask a free-form
        # question" pause via requires_user_confirmation=True) is handled by the
        # POST-execution NEEDS_USER path, NOT the pre-execution confirm-gate.
        # Its "result" is the user's reply, so it must run to emit NEEDS_USER and
        # must NOT be re-executed on resume. Excluding it here keeps that flow
        # intact and avoids a re-pause loop.
        if getattr(tool_obj, "requires_user_confirmation", False) is True:
            return False
        tier = getattr(tool_obj, "tier", None)
        if not isinstance(tier, str):
            return False
        try:
            args = json.loads(args_json)
            if not isinstance(args, dict):
                args = {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        try:
            from .tools import tool_routing_decision
            return tool_routing_decision(tool_obj, args) == "needs_confirmation"
        except Exception:
            # Fall back to the tier check alone if the routing helper or a
            # disruptive() callable raises — never let the gate crash the loop.
            return tier == "confirm"

    def _execute_tool(self, name: str, args_json: str, session_id: str) -> dict:
        if name not in self.tool_registry:
            return {"success": False, "error": f"unknown tool: {name}", "output": None}
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"invalid args JSON: {e}", "output": None}
        try:
            entry = self.tool_registry[name]
            result = entry(**args) if callable(entry) else entry.execute(args)
            return {
                "success": getattr(result, "success", True),
                "output": getattr(result, "output", str(result)),
                "actual_state_after": getattr(result, "actual_state_after", None),
                "snapshot_id": getattr(result, "snapshot_id", None),
                "error": getattr(result, "error", None),
                "requested": getattr(result, "requested", f"{name}(...)"),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "output": None}

    def _dispatch_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: str,
        tool_obj,
        call_id: str,
        session_id: str,
        snapshot_ids: list[str],
        tool_history: list[dict],
    ) -> dict:
        """Run one already-approved/allowed tool call: pre-call snapshot, then
        ActiveCalls bracketing around _execute_tool, then snapshot/history
        bookkeeping. Mutates snapshot_ids + tool_history in place and returns the
        tool_result dict. Shared by the streaming loop and the resume path so the
        confirm-gate's approved tool runs through the EXACT same machinery.
        """
        from .prefilter import cluster_id_for

        # Task 7.10: pre-call snapshot if tool declares snapshot_targets.
        # snapshot_targets_fn(args) returns a list of SnapshotTarget — if
        # non-empty, create() runs before tool dispatch so the /undo path has a
        # restore point. Failures are swallowed; the tool still runs. V1 tools
        # currently declare no snapshot_targets (NOOP today; activates when
        # kodi_addons/kodi_settings register them).
        snapshot_id_for_call = None
        if tool_obj is not None and getattr(tool_obj, "snapshot_targets_fn", None):
            try:
                args_dict = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                args_dict = {}
            try:
                targets = tool_obj.snapshot_targets_fn(args_dict)
                if targets:
                    from . import snapshot_manager
                    snapshot_id_for_call = snapshot_manager.create(
                        label=f"pre_{tool_name}",
                        targets=targets,
                        session_id=session_id,
                    )
            except Exception:
                # Snapshot failure → log + continue; tool may still need to run.
                # The tool itself decides whether to refuse without a snapshot.
                snapshot_id_for_call = None

        # ---- ActiveCalls loop-prevention bracketing (criterion C) ----
        # Before a tool runs, register it as an "active call" scoped to the
        # addon(s) it targets (from the tool's target_addons_fn). T2's
        # log_watcher.is_active() / last_window_targets() consult active_calls to
        # BUFFER + then DISCARD the log lines our own mutation produces (e.g.
        # "add-on X disabled") so they do NOT surface as a fresh incident →
        # triage → reasoner loop (spec §1.3). After the tool returns we schedule
        # removal with the built-in 1s linger to catch delayed/async log flushes.
        #
        # Read-only tools target no addons; registering them is cheap and
        # harmless (is_active() still buffers during the window, but read-only
        # tools don't write the ERROR lines that would otherwise surface). We
        # bracket every tool uniformly so the window also covers incidental log
        # noise from dispatch.
        bracket_targets = self._target_addons_for(tool_obj, tool_args)
        bracketed = False
        try:
            from .concurrency import active_calls
            active_calls.add_tool(call_id, bracket_targets)
            bracketed = True
        except Exception:
            bracketed = False
        try:
            tool_result = self._execute_tool(tool_name, tool_args, session_id)
        finally:
            if bracketed:
                try:
                    from .concurrency import active_calls
                    active_calls.schedule_remove_tool(call_id, after=1.0)
                except Exception:
                    pass

        # Attach pre-call snapshot to the result (overrides any tool-supplied
        # snapshot_id only when we created one).
        if snapshot_id_for_call:
            tool_result["snapshot_id"] = snapshot_id_for_call
            snapshot_ids.append(snapshot_id_for_call)
        elif tool_result.get("snapshot_id"):
            snapshot_ids.append(tool_result["snapshot_id"])

        output_str = str(tool_result.get("output") or "")
        tool_history.append({
            "name": tool_name,
            "args_json": tool_args,
            "success": bool(tool_result.get("success")),
            "output_signature": cluster_id_for(output_str),
            "snapshot_id": tool_result.get("snapshot_id"),
            "error": tool_result.get("error"),
        })
        return tool_result

    def run_simple(self, *, messages: list[dict], task_class: str, session_id: str) -> ReasonerOutcome:
        """Single-call path for chat where reasoner has no tools to invoke."""
        model = self.router.pick(task_class)
        est = self._estimate_cost(model, messages, max_tokens=512)
        ok, reason = self.budget.pre_call_check(estimated_cost=est)
        if not ok:
            return ReasonerOutcome(final_message="", terminal_reason="budget_refused", notes=reason or "")
        try:
            res = self.llm.chat(api_key=self.api_key, model=model, messages=messages, max_tokens=512)
        except Exception as e:
            return ReasonerOutcome(final_message="", terminal_reason="error", notes=str(e))
        price = self.router.price_per_mtok(model) or (1.0, 5.0)
        actual_cost = (res.tokens_in * price[0] + res.tokens_out * price[1]) / 1_000_000
        self.budget.record_actual(actual_cost)
        self._persist_budget()
        return ReasonerOutcome(final_message=res.text, tool_calls_made=0, cost_usd=actual_cost)

    @staticmethod
    def _target_addons_for(tool_obj, args_json: str):
        """Resolve the addon target scope for ActiveCalls bracketing (criterion
        C). Returns a set[str] of addon ids, or the literal "ALL" for Kodi-wide
        changes, or an empty set when unknown.

        Reads the tool's target_addons_fn(args) (set by @tool). Robust to test
        doubles: a MagicMock target_addons_fn returns a MagicMock, which is not a
        valid scope — we coerce anything that isn't a set or the "ALL" literal to
        an empty set so log_watcher never unions garbage. None entries (e.g.
        lambda args: {args.get("addon_id")} when addon_id is missing) are dropped.
        """
        if tool_obj is None:
            return set()
        fn = getattr(tool_obj, "target_addons_fn", None)
        if not callable(fn):
            return set()
        try:
            args = json.loads(args_json)
            if not isinstance(args, dict):
                args = {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        try:
            targets = fn(args)
        except Exception:
            return set()
        if targets == "ALL":
            return "ALL"
        if isinstance(targets, set):
            return {t for t in targets if isinstance(t, str) and t}
        if isinstance(targets, (list, tuple)):
            return {t for t in targets if isinstance(t, str) and t}
        return set()

    def run_with_tools(
        self,
        *,
        initial_messages: list[dict],
        task_class: str,
        session_id: str,
        max_turns: int = 15,
        abort_event: threading.Event | None = None,
        allowed_tools: set[str] | None = None,
        approved_tool: tuple[str, str] | None = None,
    ) -> ReasonerOutcome:
        """Multi-turn tool-use loop using chat_stream + per-chunk mid-stream budget.

        Each turn streams one LLM response. If accumulated_tool_calls is non-empty
        at end of stream, execute each tool, append assistant + tool messages, and
        continue. Otherwise return the accumulated text as final.

        Confirm-gate (v0.6.0 Part 2, criterion A): BEFORE executing each tool the
        model requests, the routing decision is computed via _needs_confirmation
        (tier=="confirm" / disruptive). A tool that needs confirmation is NOT
        executed — instead the loop takes the existing needs_user pause path so
        service.py can persist SessionState and send the Telegram [Apply]/[No]
        confirm. On resume the approved tool is passed via `approved_tool`
        (name, args_json); the gate lets that exact pending tool through ONCE.

        `allowed_tools` restricts the exposed catalog (chat path; criterion E).

        Every return path carries tool_history with per-tool output_signature
        derived from prefilter.cluster_id_for (round-2 plan-review fix H7 —
        populates the field that boot_post_mortem tool-history-match reads).
        """
        from .prefilter import cluster_id_for

        if abort_event is None:
            abort_event = threading.Event()

        messages = list(initial_messages)
        tools = self._tool_schemas(allowed_tools) or None
        # The pre-approved pending tool (set on resume after the user taps
        # [Apply]). Consumed exactly once so a model that re-requests the same
        # confirm tool after approval executes it instead of re-pausing.
        pending_approval = approved_tool
        model = self.router.pick(task_class)
        snapshot_ids: list[str] = []
        tool_history: list[dict] = []
        cost = 0.0
        turns = 0

        for turns in range(1, max_turns + 1):
            # Task 5.5: global abort_event short-circuits the loop before
            # any LLM call. Set by Main on Monitor.abortRequested() (spec §1.10).
            from .concurrency import abort_event as _global_abort_event
            if _global_abort_event.is_set():
                return ReasonerOutcome(
                    final_message="",
                    terminal_reason="aborted",
                    tool_calls_made=turns - 1,
                    cost_usd=cost,
                    snapshot_ids=snapshot_ids,
                    tool_history=tool_history,
                )
            est = self._estimate_cost(model, messages, max_tokens=2048)
            ok, reason = self.budget.pre_call_check(estimated_cost=est)
            if not ok:
                return ReasonerOutcome(
                    final_message="",
                    terminal_reason="budget_refused",
                    notes=reason or "",
                    tool_calls_made=turns - 1,
                    cost_usd=cost,
                    snapshot_ids=snapshot_ids,
                    tool_history=tool_history,
                )

            accumulated_text = ""
            accumulated_tool_calls: list = []
            finish_reason = None
            final_usage: dict = {}
            tokens_streamed = 0
            price = self.router.price_per_mtok(model) or (1.0, 5.0)
            in_p, out_p = price
            try:
                for chunk_text, fr, usage, delta_tool_calls in self.llm.chat_stream(
                    api_key=self.api_key,
                    model=model,
                    messages=messages,
                    tools=tools,
                    max_tokens=2048,
                    abort_event=abort_event,
                ):
                    if chunk_text:
                        accumulated_text += chunk_text
                        tokens_streamed += max(1, len(chunk_text) // 4)
                        streamed_cost = tokens_streamed * out_p / 1_000_000
                        if not self.budget.mid_stream_check(streamed_cost=streamed_cost):
                            # Synthetic envelope per spec §5.5 / plan 5.4-REVISED:
                            # forward-compat for Task 5.6 message-replay on resume.
                            synthetic_result = {
                                "role": "tool", "tool_call_id": "budget_truncated",
                                "content": json.dumps({
                                    "error": "budget_truncated",
                                    "tokens_streamed": tokens_streamed,
                                    "estimated_cost_so_far": f"${self.budget.incident_cost_usd + streamed_cost:.4f}",
                                }),
                            }
                            messages.append({"role": "assistant", "content": "<<<budget-truncated>>>"})
                            messages.append(synthetic_result)
                            return ReasonerOutcome(
                                final_message="",
                                terminal_reason="budget_truncated",
                                notes=f"mid-stream cap trip at {tokens_streamed} tokens",
                                tool_calls_made=turns - 1,
                                cost_usd=cost,
                                snapshot_ids=snapshot_ids,
                                tool_history=tool_history,
                            )
                    if delta_tool_calls:
                        accumulated_tool_calls.extend(delta_tool_calls)
                    if fr:
                        finish_reason = fr
                    if usage:
                        final_usage = usage
            except Exception as e:
                return ReasonerOutcome(
                    final_message="",
                    terminal_reason="error",
                    notes=str(e),
                    tool_calls_made=turns - 1,
                    cost_usd=cost,
                    snapshot_ids=snapshot_ids,
                    tool_history=tool_history,
                )

            actual = (
                final_usage.get("prompt_tokens", 0) * in_p
                + final_usage.get("completion_tokens", 0) * out_p
            ) / 1_000_000
            cost += actual
            self.budget.record_actual(actual)
            self._persist_budget()

            if accumulated_tool_calls:
                for tc in accumulated_tool_calls:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    tool_args = fn.get("arguments", "{}")
                    tool_obj = self.tool_registry.get(tool_name)

                    # ---- Confirm-gate (v0.6.0 Part 2, criterion A) ----
                    # Compute the routing decision BEFORE any snapshot or
                    # execution. If the tool needs confirmation and it is NOT the
                    # pre-approved pending tool, DO NOT execute it: append the
                    # assistant tool_calls message (so the resume replay sees the
                    # request) and take the existing needs_user pause path. The
                    # caller's pause/Telegram-[Apply]/[No]/resume flow then runs.
                    #
                    # The `approved_tool` (set on resume) is matched by exact
                    # (name, args) and consumed once — this is the TOCTOU
                    # re-check (A3): after approval we execute the approved tool
                    # exactly once; we do NOT re-evaluate whether it still needs
                    # confirmation (it does — that's why it was approved). Any
                    # OTHER confirm tool the model requests still pauses.
                    is_approved = (
                        pending_approval is not None
                        and pending_approval[0] == tool_name
                        and pending_approval[1] == tool_args
                    )
                    if is_approved:
                        # Consume the one-shot approval so a second confirm tool
                        # in the same turn (or a later turn) still gates.
                        pending_approval = None
                    elif self._needs_confirmation(tool_obj, tool_args):
                        messages.append({"role": "assistant", "tool_calls": [tc]})
                        return ReasonerOutcome(
                            final_message="",
                            terminal_reason="needs_user",
                            tool_calls_made=turns - 1,
                            cost_usd=cost,
                            snapshot_ids=snapshot_ids,
                            tool_history=tool_history,
                            pending_tool=tool_name,
                            pending_args=tool_args,
                            messages_so_far=list(messages),
                        )

                    call_id = tc.get("id") or f"{tool_name}_{turns}"
                    tool_result = self._dispatch_tool_call(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_obj=tool_obj,
                        call_id=call_id,
                        session_id=session_id,
                        snapshot_ids=snapshot_ids,
                        tool_history=tool_history,
                    )

                    messages.append({"role": "assistant", "tool_calls": [tc]})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(tool_result),
                    })

                    # Task 5.5: pause if tool requires user confirmation.
                    # Trigger sources: tool.requires_user_confirmation is True OR
                    # tool returned error=='NEEDS_USER' (spec §1.7). This is the
                    # LEGACY "ask a free-form question" path (ask_user) — distinct
                    # from the v0.6.0 confirm-gate above, which fires BEFORE
                    # execution for tier=confirm/disruptive mutation tools. ask_user
                    # is deliberately excluded from the pre-gate (see
                    # _needs_confirmation) so it runs, emits NEEDS_USER, and pauses
                    # here; on resume its user_reply becomes the tool output.
                    # Strict `is True` check — MagicMock attrs return MagicMock
                    # (truthy) by default, so a bare `if needs_pause` would
                    # spuriously pause in tests that never set this marker.
                    needs_pause = (
                        getattr(tool_obj, "requires_user_confirmation", False) is True
                    )
                    if needs_pause or tool_result.get("error") == "NEEDS_USER":
                        return ReasonerOutcome(
                            final_message="",
                            terminal_reason="needs_user",
                            tool_calls_made=turns,
                            cost_usd=cost,
                            snapshot_ids=snapshot_ids,
                            tool_history=tool_history,
                            pending_tool=tool_name,
                            pending_args=tool_args,
                            messages_so_far=list(messages),
                        )
                continue

            return ReasonerOutcome(
                final_message=accumulated_text,
                tool_calls_made=turns - 1,
                cost_usd=cost,
                snapshot_ids=snapshot_ids,
                tool_history=tool_history,
            )

        return ReasonerOutcome(
            final_message="",
            terminal_reason="max_turns",
            tool_calls_made=turns,
            cost_usd=cost,
            snapshot_ids=snapshot_ids,
            tool_history=tool_history,
            notes=f"hit max_turns={max_turns}",
        )

    def resume_from(
        self,
        *,
        state,
        user_reply,
        task_class: str,
        max_turns: int = 15,
        allowed_tools: set[str] | None = None,
    ) -> ReasonerOutcome:
        """Resume a paused session with the user's reply to the pending tool.

        Reconstructs the message history captured in SessionState, appends a
        tool-role message carrying the user_reply (so the model sees it as the
        tool's belated output), and continues the run_with_tools loop.

        Confirm-gate resume (v0.6.0 Part 2, criteria A3 + F): when the pause was a
        confirm-gate pause (a tier=confirm/disruptive mutation that did NOT
        execute) and the user APPROVED (user_reply is True), the previously
        pending tool is executed HERE, directly — we do not depend on the model
        re-requesting it. Its real ToolResult is appended as the tool message for
        the gate's pending assistant tool_calls, then the loop runs once more so
        the model produces the completion ("Done - ..."). This is the TOCTOU
        re-check point (A3): we execute the approved tool exactly once and do not
        re-gate it (approval is the authorization).

        On decline (user_reply is False) the tool is NOT executed; the model sees
        a {"user_reply": False} tool message and chooses another path.

        The legacy ask_user path (which DID execute and emitted NEEDS_USER) is
        unaffected: its "result" is the user's reply, so we append the user_reply
        tool message and let the model continue (the pre-gate excludes ask_user,
        and there is no pending mutation to execute).

        Spec: §1.7 (pause/resume sequence).
        """
        messages = list(state.messages)

        pt = state.pending_tool if isinstance(state.pending_tool, dict) else None
        pend_name = pt.get("name") if pt else None
        pend_args = pt.get("args") if pt else None

        # Did the pending tool actually execute before the pause? The legacy
        # ask_user/NEEDS_USER path executes (so a tool result is already in
        # messages); the confirm-gate path does NOT execute (the trailing message
        # is an assistant tool_calls with no following tool result). Detect the
        # gate case: a real pending mutation name + args + a trailing assistant
        # tool_calls message that hasn't been answered yet.
        gate_pending_tc_id = None
        if pend_name and pend_args is not None:
            tool_obj = self.tool_registry.get(pend_name)
            # Only mutation tools that the pre-gate would have stopped qualify;
            # ask_user (requires_user_confirmation) is excluded.
            if self._needs_confirmation(tool_obj, pend_args):
                for m in reversed(messages):
                    if m.get("role") == "tool":
                        break  # already answered → not a gate pause
                    if m.get("role") == "assistant" and m.get("tool_calls"):
                        tcs = m.get("tool_calls") or []
                        if tcs:
                            last_tc = tcs[-1]
                            fn = last_tc.get("function", {})
                            if (fn.get("name") == pend_name
                                    and fn.get("arguments") == pend_args):
                                gate_pending_tc_id = last_tc.get("id", "") or "approved"
                        break

        if gate_pending_tc_id is not None and user_reply is True:
            # APPROVED confirm-gate tool → execute it directly, exactly once.
            snapshot_ids = list(getattr(state, "snapshot_ids", []) or [])
            tool_history = list(getattr(state, "tool_history", []) or [])
            tool_obj = self.tool_registry.get(pend_name)
            tool_result = self._dispatch_tool_call(
                tool_name=pend_name,
                tool_args=pend_args,
                tool_obj=tool_obj,
                call_id=gate_pending_tc_id,
                session_id=state.session_id,
                snapshot_ids=snapshot_ids,
                tool_history=tool_history,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": gate_pending_tc_id,
                "content": json.dumps(tool_result),
            })
            out = self.run_with_tools(
                initial_messages=messages,
                task_class=task_class,
                session_id=state.session_id,
                max_turns=max_turns,
                allowed_tools=allowed_tools,
            )
            # Fold the pre-loop execution's snapshots/history into the outcome so
            # /undo + tool-history-match see the approved tool's effect.
            merged_snaps = snapshot_ids + [
                s for s in out.snapshot_ids if s not in snapshot_ids
            ]
            out.snapshot_ids = merged_snaps
            out.tool_history = tool_history + list(out.tool_history)
            out.tool_calls_made = out.tool_calls_made + 1
            return out

        # Decline, or a legacy ask_user/NEEDS_USER pause, or nothing pending:
        # surface the user's reply as the pending tool's belated output and let
        # the model continue.
        if state.pending_tool:
            messages.append({
                "role": "tool",
                "tool_call_id": gate_pending_tc_id or "user_resume",
                "content": json.dumps({"user_reply": user_reply}),
            })
        return self.run_with_tools(
            initial_messages=messages,
            task_class=task_class,
            session_id=state.session_id,
            max_turns=max_turns,
            allowed_tools=allowed_tools,
        )
