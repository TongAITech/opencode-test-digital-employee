from __future__ import annotations

from typing import Protocol

from .contracts import R48AuthorityOperation, R48AuthorityResult


class R48AuthorityPort(Protocol):
    def submit(self, operation: R48AuthorityOperation, *, idempotency_key: str, correlation_id: str) -> R48AuthorityResult:
        ...

    def observe(self, operation: R48AuthorityOperation, *, correlation_id: str) -> R48AuthorityResult:
        ...

    def reconcile(self, operation: R48AuthorityOperation, *, idempotency_key: str, correlation_id: str) -> R48AuthorityResult:
        ...


__all__ = ["R48AuthorityPort"]
