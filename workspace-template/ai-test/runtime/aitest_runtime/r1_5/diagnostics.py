from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import REPORT_SCHEMA_VERSION, R1_5_CONTRACT_VERSION, R15Error, redact, utc_now


_SENSITIVE_TEXT = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|authorization|cookie)\s*[:=]\s*\S+")


def _safe_message(value: str) -> str:
    return _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}=<redacted>", value)


@dataclass(frozen=True)
class DiagnosticReport:
    correlation_id: str
    code: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)
    report_schema_version: str = REPORT_SCHEMA_VERSION
    contract_version: str = R1_5_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.correlation_id:
            raise R15Error("DIAGNOSTIC_CORRELATION_REQUIRED", "diagnostics require a correlation id")

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "report_schema_version": self.report_schema_version,
            "contract_version": self.contract_version,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "message": _safe_message(self.message),
            "evidence": redact(dict(self.evidence)),
            "observed_at": self.observed_at,
            "canonical": False,
            "truth_source": None,
        }
        if include_digest:
            result["digest"] = canonical_sha256(result)
        return result


def diagnose_failure(
    error: Exception,
    *,
    correlation_id: str,
    evidence: Mapping[str, Any] | None = None,
) -> DiagnosticReport:
    if isinstance(error, R15Error):
        code, message, details = error.code, error.message, error.details
    else:
        code, message, details = type(error).__name__.upper(), "operation failed", {"exception_type": type(error).__name__}
    return DiagnosticReport(
        correlation_id=correlation_id,
        code=code,
        message=message,
        evidence={"details": details, **dict(evidence or {})},
    )
