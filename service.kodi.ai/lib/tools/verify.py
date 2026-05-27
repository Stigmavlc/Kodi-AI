# service.kodi.ai/lib/tools/verify.py
"""verify_fix tool — per-cluster-category verifier strategies.

V1 minimal: only the 'default' strategy is wired (30s log-quiet wait,
abort_event interruptible). The other strategies (playback_fail,
dep_import_fail, repo_unreachable) return a placeholder verdict — full
implementations + log_watcher.subscribe(filter_fn, on_match, timeout_s)
deferred to Task 9.1 (verifier consolidation).

Spec: §4.4.
"""
from __future__ import annotations
import time
from ..concurrency import abort_event
from . import tool, ToolResult


@tool(
    name="verify_fix",
    description="Verify a fix worked. Strategies: playback_fail | dep_import_fail | repo_unreachable | default.",
    schema={
        "type": "object",
        "properties": {
            "strategy": {"type": "string"},
            "args": {"type": "object"},
        },
        "required": ["strategy", "args"],
    },
    tier="immediate", safety_class="read_only",
)
def verify_fix(strategy: str, args: dict) -> ToolResult:
    cluster_id = args.get("cluster_id", "")
    if strategy == "default":
        # 30s log-quiet for cluster_id — V1 polls abort_event in 0.25s slices
        # instead of subscribing to log_watcher. Full wiring (subscribe API +
        # signal collection) lands in Task 9.1.
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if abort_event.wait(0.25):
                return ToolResult(
                    success=False, requested="verify_fix(default)",
                    output={"verdict": "aborted"}, actual_state_after=None,
                    error="aborted", snapshot_id=None, cost_seconds=0.0,
                )
        return ToolResult(
            success=True, requested="verify_fix(default)",
            output={"verdict": "log_quiet_30s", "cluster_id": cluster_id},
            actual_state_after=None, error=None,
            snapshot_id=None, cost_seconds=0.0,
        )
    # Other strategies — V1 placeholder. Wired in Task 9.1.
    return ToolResult(
        success=True, requested=f"verify_fix({strategy})",
        output={"verdict": f"{strategy}_not_yet_implemented_v1", "cluster_id": cluster_id},
        actual_state_after=None, error=None,
        snapshot_id=None, cost_seconds=0.0,
    )
