from __future__ import annotations

from typing import Any, Mapping


class R37Error(RuntimeError):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}
