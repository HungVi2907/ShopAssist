"""Crash-safe per-attempt budget ledger shared by Gateway experiments."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import uuid

from shopassist.llm_gateway.errors import DispatchBudgetDenied
from shopassist.llm_gateway.schemas import GatewayUsage


ExperimentBudgetExceeded = DispatchBudgetDenied


class PersistentExperimentBudget:
    VERSION = 1

    def __init__(self, path: Path, max_requests: int, max_tokens: int):
        if max_requests < 0 or max_tokens < 0:
            raise ValueError("Budgets must be nonnegative")
        self.path = Path(path)
        self.max_requests = max_requests
        self.max_tokens = max_tokens
        self._lock = threading.RLock()
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("version") is None and {"requests", "charged_tokens", "observed_tokens"} <= set(state):
                # Upgrade the prior Phase 8.2 budget shape without resetting
                # historical charges. Pending old requests are unknown usage.
                self.requests = int(state["requests"])
                self.charged_tokens = int(state["charged_tokens"])
                self.observed_tokens = int(state["observed_tokens"])
                self.unknown_usage_attempts = 0
                self.reservations = {}
                self._save()
            elif state.get("version") != self.VERSION:
                raise ValueError("Unsupported experiment budget ledger version")
            else:
                self.requests = state["requests"]
                self.charged_tokens = state["charged_tokens"]
                self.observed_tokens = state["observed_tokens"]
                self.reservations = state["reservations"]
                self.unknown_usage_attempts = state.get("unknown_usage_attempts", 0)
            # On restart, dispatched-but-unsettled attempts retain the reserved
            # token charge; undispatched reservations had no outbound attempt.
            for token, item in tuple(self.reservations.items()):
                if item["dispatched"]:
                    self.charged_tokens += item["reserved_tokens"]
                    self.unknown_usage_attempts += 1
                del self.reservations[token]
            self._save()
        else:
            self.requests = 0
            self.charged_tokens = 0
            self.observed_tokens = 0
            self.unknown_usage_attempts = 0
            self.reservations: dict[str, dict] = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "max_requests": self.max_requests,
            "max_tokens": self.max_tokens,
            "requests": self.requests,
            "charged_tokens": self.charged_tokens,
            "observed_tokens": self.observed_tokens,
            "unknown_usage_attempts": self.unknown_usage_attempts,
            "reservations": self.reservations,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def reserve(self, task_id: str, route_id: str, estimated_tokens: int | None) -> str:
        with self._lock:
            estimate = max(0, int(estimated_tokens or 0))
            held_requests = sum(not item["dispatched"] for item in self.reservations.values())
            held_tokens = sum(item["reserved_tokens"] for item in self.reservations.values())
            if self.requests + held_requests >= self.max_requests:
                raise DispatchBudgetDenied("Experiment request ceiling exhausted")
            if self.charged_tokens + held_tokens + estimate > self.max_tokens:
                raise DispatchBudgetDenied("Experiment token ceiling exhausted")
            token = uuid.uuid4().hex
            self.reservations[token] = {
                "task_id": task_id, "route_id": route_id,
                "reserved_tokens": estimate, "dispatched": False,
            }
            self._save()
            return token

    def mark_dispatched(self, token: str) -> None:
        with self._lock:
            item = self.reservations.get(token)
            if item is None or item["dispatched"]:
                raise RuntimeError("Invalid experiment budget reservation")
            item["dispatched"] = True
            self.requests += 1
            self._save()

    def release(self, token: str) -> None:
        """Release only a reservation that has not crossed dispatch."""
        with self._lock:
            item = self.reservations.get(token)
            if item is None:
                return
            if item["dispatched"]:
                self.settle(token, None)
                return
            del self.reservations[token]
            self._save()

    def settle(self, token: str, usage: GatewayUsage | None) -> None:
        """Settle once; unknown usage retains the conservative reservation."""
        with self._lock:
            item = self.reservations.get(token)
            if item is None:
                return
            if not item["dispatched"]:
                del self.reservations[token]
                self._save()
                return
            actual = None
            if usage is not None:
                actual = usage.total_tokens
                if actual is None and usage.input_tokens is not None and usage.output_tokens is not None:
                    actual = usage.input_tokens + usage.output_tokens
            estimate = item["reserved_tokens"]
            self.charged_tokens += estimate if actual is None else actual
            if actual is not None:
                self.observed_tokens += actual
            else:
                self.unknown_usage_attempts += 1
            del self.reservations[token]
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests": self.requests,
                "charged_tokens": self.charged_tokens,
                "observed_tokens": self.observed_tokens,
                "unknown_usage_attempts": self.unknown_usage_attempts,
                "pending_reservations": len(self.reservations),
            }
