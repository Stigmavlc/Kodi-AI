"""BudgetGuard: 3-tier cost enforcement.

Per-incident hard cap (reset per session_start), daily, monthly.
3-point per-incident enforcement: pre-call estimate, mid-stream check at
100% trip, post-call record_actual.

Daily/monthly persisted to addon_data/budget_counters.json.
Reset wall-clock per user-configured timezone (handled at boundary by
caller; this class just tracks counters).

Spec: §5.5.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from .. import state_paths

_LOCK = threading.Lock()


class BudgetGuard:
    def __init__(
        self,
        *,
        per_incident_cap: float,
        daily_cap: float,
        monthly_cap: float,
    ):
        self.per_incident_cap = per_incident_cap
        self.daily_cap = daily_cap
        self.monthly_cap = monthly_cap
        self.incident_cost_usd = 0.0
        self.daily_cost_usd = 0.0
        self.monthly_cost_usd = 0.0
        self.day_iso: str = datetime.now(timezone.utc).date().isoformat()
        self.month_iso: str = self.day_iso[:7]  # "2026-05"

    def _path(self) -> str:
        return state_paths.profile_path("budget_counters.json")

    def load(self) -> None:
        with _LOCK:
            p = self._path()
            if not os.path.exists(p):
                return
            try:
                with open(p, "r", encoding="utf-8") as f:
                    blob = json.load(f)
            except (json.JSONDecodeError, OSError):
                return
            today = datetime.now(timezone.utc).date().isoformat()
            this_month = today[:7]
            self.daily_cost_usd = blob.get("daily", 0.0) if blob.get("day") == today else 0.0
            self.monthly_cost_usd = blob.get("monthly", 0.0) if blob.get("month") == this_month else 0.0
            self.day_iso = today
            self.month_iso = this_month

    def persist(self) -> None:
        with _LOCK:
            blob = {
                "day": self.day_iso,
                "daily": self.daily_cost_usd,
                "month": self.month_iso,
                "monthly": self.monthly_cost_usd,
            }
            state_paths.atomic_write(self._path(), json.dumps(blob).encode("utf-8"))

    def pre_call_check(self, *, estimated_cost: float) -> tuple[bool, str | None]:
        """Returns (ok, reason). reason names the cap that would trip."""
        with _LOCK:
            if self.incident_cost_usd + estimated_cost > self.per_incident_cap:
                return False, f"per_incident cap ${self.per_incident_cap:.2f} would be exceeded"
            if self.daily_cost_usd + estimated_cost > self.daily_cap:
                return False, f"daily cap ${self.daily_cap:.2f} would be exceeded"
            if self.monthly_cost_usd + estimated_cost > self.monthly_cap:
                return False, f"monthly cap ${self.monthly_cap:.2f} would be exceeded"
            return True, None

    def mid_stream_check(self, *, streamed_cost: float) -> bool:
        """Returns True if still within cap, False if trip at exactly 100%."""
        with _LOCK:
            return self.incident_cost_usd + streamed_cost <= self.per_incident_cap

    def record_actual(self, cost_usd: float) -> None:
        with _LOCK:
            self.incident_cost_usd += cost_usd
            self.daily_cost_usd += cost_usd
            self.monthly_cost_usd += cost_usd

    def reset_incident(self) -> None:
        with _LOCK:
            self.incident_cost_usd = 0.0
