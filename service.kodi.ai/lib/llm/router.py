"""TaskModelRouter — Auto / Manual mode + per-task ordered fallback.

Loads recommended_models.json at instantiation; user_override_json from
addon setting models_override merges (override per-class, not per-model).

Spec: §4.5.
"""
from __future__ import annotations
import json
import os
from typing import Literal

TaskClass = Literal["t0_triage", "t1_simple", "t2_reason", "t3_heroic"]


def _default_models_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", "resources", "data", "recommended_models.json")


class TaskModelRouter:
    def __init__(
        self,
        *,
        mode: Literal["auto", "manual"],
        manual_model: str = "",
        user_override_json: str = "",
        models_path: str | None = None,
    ):
        self.mode = mode
        self.manual_model = manual_model
        path = models_path or _default_models_path()
        with open(path, "r", encoding="utf-8") as f:
            defaults: dict[str, list[dict]] = json.load(f)
        if user_override_json:
            try:
                override = json.loads(user_override_json)
                # Per-class replacement (not per-model deep merge)
                for k, v in override.items():
                    defaults[k] = v
            except json.JSONDecodeError:
                pass  # silently ignore malformed override; user notified in /status
        self._chains: dict[str, list[dict]] = defaults
        # Flatten model → (price_in, price_out) for O(1) lookup
        self._prices: dict[str, tuple[float, float]] = {}
        for chain in defaults.values():
            for m in chain:
                self._prices[m["id"]] = (m["price_in"], m["price_out"])

    def pick(self, task_class: str) -> str:
        if self.mode == "manual":
            return self.manual_model
        if task_class not in self._chains:
            raise KeyError(f"unknown task class: {task_class}")
        return self._chains[task_class][0]["id"]

    def next_fallback(self, task_class: str, current_model: str) -> str | None:
        """Return next model in fallback chain after current_model, or None."""
        if self.mode == "manual":
            return None  # manual mode has no fallback
        if task_class not in self._chains:
            return None
        chain = [m["id"] for m in self._chains[task_class]]
        try:
            idx = chain.index(current_model)
        except ValueError:
            return None
        if idx + 1 >= len(chain):
            return None
        return chain[idx + 1]

    def price_per_mtok(self, model: str) -> tuple[float, float] | None:
        """Returns (input_price_per_Mtok, output_price_per_Mtok) or None."""
        return self._prices.get(model)

    def all_model_ids(self) -> set[str]:
        """For slug validation against OpenRouter /models."""
        return set(self._prices.keys())
