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

    def _tool_schemas(self) -> list[dict]:
        return [t.schema_dict() for t in self.tool_registry.values() if hasattr(t, "schema_dict")]

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

    def run_with_tools(
        self,
        *,
        initial_messages: list[dict],
        task_class: str,
        session_id: str,
        max_turns: int = 15,
        abort_event: threading.Event | None = None,
    ) -> ReasonerOutcome:
        """Multi-turn tool-use loop using chat_stream + per-chunk mid-stream budget.

        Each turn streams one LLM response. If accumulated_tool_calls is non-empty
        at end of stream, execute each tool, append assistant + tool messages, and
        continue. Otherwise return the accumulated text as final.

        Every return path carries tool_history with per-tool output_signature
        derived from prefilter.cluster_id_for (round-2 plan-review fix H7 —
        populates the field that boot_post_mortem tool-history-match reads).
        """
        from .prefilter import cluster_id_for

        if abort_event is None:
            abort_event = threading.Event()

        messages = list(initial_messages)
        tools = self._tool_schemas() or None
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

                    # Task 7.10: pre-call snapshot if tool declares snapshot_targets.
                    # snapshot_targets_fn(args) returns a list of SnapshotTarget — if
                    # non-empty, create() runs before tool dispatch so the /undo path
                    # has a restore point. Failures are swallowed; the tool still runs.
                    # V1 tools currently declare no snapshot_targets (NOOP today;
                    # activates when kodi_addons/kodi_settings register them).
                    snapshot_id_for_call = None
                    tool_obj = self.tool_registry.get(tool_name)
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

                    tool_result = self._execute_tool(
                        tool_name,
                        tool_args,
                        session_id,
                    )
                    # Attach pre-call snapshot to the result (overrides any
                    # tool-supplied snapshot_id only when we created one).
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

                    messages.append({"role": "assistant", "tool_calls": [tc]})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(tool_result),
                    })

                    # Task 5.5: pause if tool requires user confirmation.
                    # Trigger sources: tool.requires_user_confirmation is True OR
                    # tool returned error=='NEEDS_USER' (spec §1.7). On pause we
                    # capture pending_tool/pending_args + full messages_so_far
                    # so service.py can persist SessionState and ask the user.
                    # Strict `is True` check — MagicMock attrs return MagicMock
                    # (truthy) by default, so a bare `if needs_pause` would
                    # spuriously pause in tests that never set this marker.
                    tool_obj = self.tool_registry.get(tool_name)
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
    ) -> ReasonerOutcome:
        """Resume a paused session with the user's reply to the pending tool.

        Reconstructs the message history captured in SessionState, appends a
        tool-role message carrying the user_reply (so the model sees it as the
        tool's belated output), and continues the run_with_tools loop.

        Spec: §1.7 (pause/resume sequence).
        """
        messages = list(state.messages)
        if state.pending_tool:
            messages.append({
                "role": "tool",
                "tool_call_id": "user_resume",
                "content": json.dumps({"user_reply": user_reply}),
            })
        return self.run_with_tools(
            initial_messages=messages,
            task_class=task_class,
            session_id=state.session_id,
            max_turns=max_turns,
        )
