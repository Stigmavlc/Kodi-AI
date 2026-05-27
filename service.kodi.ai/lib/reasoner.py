"""Reasoner: LLM tool-use agent loop. T4-owned single-threaded.

Skeleton in 5.3: simple non-tool path (one LLM call → final_message).
Full agent loop with tool dispatch + pause/resume in Task 5.4-5.5.

Spec: §1.6, §1.7, §3.1, §3.3.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasonerOutcome:
    final_message: str
    tool_calls_made: int = 0
    terminal_reason: str = "complete"  # complete | budget_refused | needs_user | aborted | error
    notes: str = ""
    cost_usd: float = 0.0
    snapshot_ids: list[str] = field(default_factory=list)


class Reasoner:
    def __init__(self, *, llm_client, api_key: str, router, budget):
        self.llm = llm_client
        self.api_key = api_key
        self.router = router
        self.budget = budget

    def _estimate_cost(self, model: str, messages: list[dict], max_tokens: int) -> float:
        price = self.router.price_per_mtok(model) or (1.0, 5.0)
        in_p, out_p = price
        approx_in_tokens = sum(len(m.get("content") or "") for m in messages) / 4
        return (approx_in_tokens * in_p + max_tokens * out_p) / 1_000_000

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
        return ReasonerOutcome(final_message=res.text, tool_calls_made=0, cost_usd=actual_cost)
