from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.common import redact


REQUIRED_CHECKS = tuple(f"E3-VS-{index:02d}" for index in range(1, 14))


@dataclass(frozen=True)
class VerticalSliceGateResult:
    status: str
    evidence_mode: str
    checks: tuple[Mapping[str, Any], ...]
    closure_receipt: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return redact({
            "gate": "R3_E3_CONTROLLED_BROWSER_RUNTIME_VERTICAL_SLICE_GATE",
            "status": self.status,
            "evidence_mode": self.evidence_mode,
            "checks": list(self.checks),
            "closure_receipt": dict(self.closure_receipt),
        })


def _check_passed(value: Any) -> bool:
    if isinstance(value, Mapping):
        if str(value.get("status", "")).upper() not in {"PASS", "READY", "APPLIED", "TRUE"}:
            return False
        if value.get("evidence_mode") != "REAL_RUNTIME" and value.get("real_runtime") is not True:
            return False
        if value.get("real_runtime") is False or str(value.get("adapter_kind", "")).upper() in {"MOCK", "FAKE", "NOT_CONFIGURED"}:
            return False
        if value.get("mock_result") is not None or value.get("fake") is True:
            return False
        return True
    return value is True


def evaluate_vertical_slice_gate(*, evidence_mode: str, checks: Mapping[str, Any]) -> VerticalSliceGateResult:
    """Evaluate the sole E3 closure gate without treating structural fixtures as real runtime."""

    mode = str(evidence_mode).upper()
    rows = []
    failures: list[str] = []
    for check_id in REQUIRED_CHECKS:
        value = checks.get(check_id)
        passed = mode == "REAL_RUNTIME" and _check_passed(value)
        row = {"id": check_id, "status": "PASS" if passed else "FAIL", "evidence": value}
        rows.append(row)
        if not passed:
            failures.append(check_id)
    status = "PASS" if not failures and mode == "REAL_RUNTIME" else "BLOCKED"
    receipt = {
        "gate": "R3_E3_CONTROLLED_BROWSER_RUNTIME_VERTICAL_SLICE_GATE",
        "status": status,
        "evidence_mode": mode,
        "failed_checks": failures,
        "mock_or_fake_counts_as_pass": False,
    }
    return VerticalSliceGateResult(status, mode, tuple(rows), receipt)
