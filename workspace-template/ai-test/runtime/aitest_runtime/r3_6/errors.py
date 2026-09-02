from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError


class R36Error(RuntimeError):
    """R3.6 typed boundary, investigation, evidence, and truth-assessment error."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code, message, details or {})
