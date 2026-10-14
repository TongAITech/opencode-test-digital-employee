from __future__ import annotations

import collections
import time
from dataclasses import dataclass
from typing import Deque, Dict, Optional


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    action: str
    reason: str
    retry_after_seconds: int = 0


class ContextBudget:
    """Pre-request context guard. Capacity is configured, not version-pinned."""

    def __init__(self, capacity_tokens: int, soft_ratio: float = 0.72, hard_ratio: float = 0.86):
        if capacity_tokens <= 0:
            raise ValueError("capacity_tokens must be positive")
        if not 0 < soft_ratio < hard_ratio < 1:
            raise ValueError("invalid context ratios")
        self.capacity = int(capacity_tokens)
        self.soft = int(self.capacity * soft_ratio)
        self.hard = int(self.capacity * hard_ratio)

    def decide(self, current_tokens: int, incoming_tokens: int, reserved_output_tokens: int) -> BudgetDecision:
        projected = max(0, current_tokens) + max(0, incoming_tokens) + max(0, reserved_output_tokens)
        if projected >= self.hard:
            return BudgetDecision(False, "ROTATE_SESSION", "CONTEXT_HARD_LIMIT_PREVENTED")
        if projected >= self.soft:
            return BudgetDecision(False, "ARTIFACTIZE_OR_SPLIT", "CONTEXT_SOFT_LIMIT_PREVENTED")
        return BudgetDecision(True, "ALLOW", "WITHIN_CONTEXT_BUDGET")


class ProviderBudget:
    """Global request governor with rolling-window quota and provider cooldown."""

    def __init__(self, max_requests: int, window_seconds: int, max_inflight: int = 4):
        if max_requests <= 0 or window_seconds <= 0 or max_inflight <= 0:
            raise ValueError("budget parameters must be positive")
        self.max_requests = int(max_requests)
        self.window_seconds = int(window_seconds)
        self.max_inflight = int(max_inflight)
        self._requests: Deque[float] = collections.deque()
        self._inflight = 0
        self._cooldowns: Dict[str, float] = {}

    def admit(self, provider: str, now: Optional[float] = None) -> BudgetDecision:
        t = time.time() if now is None else float(now)
        self._purge(t)
        cooldown_until = self._cooldowns.get(provider, 0.0)
        if cooldown_until > t:
            return BudgetDecision(False, "BACKPRESSURE", "PROVIDER_COOLDOWN", int(cooldown_until - t + 0.999))
        if self._inflight >= self.max_inflight:
            return BudgetDecision(False, "BACKPRESSURE", "GLOBAL_CONCURRENCY_LIMIT", 1)
        if len(self._requests) >= self.max_requests:
            retry = int(self._requests[0] + self.window_seconds - t + 0.999)
            return BudgetDecision(False, "BACKPRESSURE", "GLOBAL_REQUEST_WINDOW_EXHAUSTED", max(1, retry))
        self._requests.append(t)
        self._inflight += 1
        return BudgetDecision(True, "ALLOW", "REQUEST_RESERVED")

    def complete(self) -> None:
        self._inflight = max(0, self._inflight - 1)

    def provider_error(self, provider: str, status_code: int, retry_after_seconds: int = 0, now: Optional[float] = None) -> None:
        t = time.time() if now is None else float(now)
        if status_code == 429:
            self._cooldowns[provider] = max(self._cooldowns.get(provider, 0.0), t + max(1, retry_after_seconds or 60))
        elif status_code == 451:
            self._cooldowns[provider] = max(self._cooldowns.get(provider, 0.0), t + max(60, retry_after_seconds or 3600))

    def snapshot(self, now: Optional[float] = None) -> dict:
        t = time.time() if now is None else float(now)
        self._purge(t)
        return {
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "used_requests": len(self._requests),
            "available_requests": max(0, self.max_requests - len(self._requests)),
            "inflight": self._inflight,
            "max_inflight": self.max_inflight,
            "cooldowns": {k: v for k, v in self._cooldowns.items() if v > t},
        }

    def _purge(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        expired = [p for p, until in self._cooldowns.items() if until <= now]
        for p in expired:
            self._cooldowns.pop(p, None)
