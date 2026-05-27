# service.kodi.ai/lib/tools/__init__.py
"""Tool registry + @tool decorator + ToolResult.

Per spec §1.9 / §4.1: each tool declares tier (immediate | confirm),
disruptive (callable), target_addons (callable), snapshot_targets (callable | None).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class ToolResult:
    success: bool
    requested: str
    output: Any | None
    actual_state_after: Any | None
    error: str | None
    snapshot_id: str | None
    cost_seconds: float
    warning: str | None = None


registry: dict[str, Callable] = {}


def tool(
    *,
    name: str,
    description: str,
    schema: dict,
    tier: Literal["immediate", "confirm"],
    disruptive: Callable[[dict], bool] = lambda args: False,
    target_addons: Callable[[dict], set[str]] = lambda args: set(),
    snapshot_targets: Callable[[dict], list] | None = None,
    safety_class: Literal["read_only", "low_risk", "medium_risk", "high_risk"] = "low_risk",
) -> Callable:
    def deco(fn: Callable) -> Callable:
        fn.tool_name = name
        fn.description = description
        fn.tool_schema = schema
        fn.tier = tier
        fn.disruptive_fn = disruptive
        fn.target_addons_fn = target_addons
        fn.snapshot_targets_fn = snapshot_targets
        fn.safety_class = safety_class
        registry[name] = fn
        return fn
    return deco


def tool_routing_decision(fn: Callable, args: dict) -> str:
    """Return 'apply_immediately' or 'needs_confirmation'."""
    if fn.tier == "confirm":
        return "needs_confirmation"
    if fn.disruptive_fn(args):
        return "needs_confirmation"
    return "apply_immediately"
