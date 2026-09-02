from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError


class R35Error(RuntimeError):
    """R3.5 schema, boundary, durability and verification error."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code, message, details or {})

