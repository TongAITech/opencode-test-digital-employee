from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from . import rc72_n6_executable_readiness_core as _core

ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT = _core.ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT
EVENT_N6_EXECUTABLE_CONTRACT_COMPILED = _core.EVENT_N6_EXECUTABLE_CONTRACT_COMPILED
N6_SCHEMA_VERSION = _core.N6_SCHEMA_VERSION

ReadinessViolation = _core.ReadinessViolation
ExecutableReadinessError = _core.ExecutableReadinessError
ExecutableContract = _core.ExecutableContract

_RUNTIME_BINDING_VIOLATION_CODES = {
    "N6_REQUEST_SCHEMA_UNRESOLVED",
    "N6_REQUEST_UNRESOLVED",
}


class N6ExecutableReadinessCompiler(_core.N6ExecutableReadinessCompiler):
    """Public N6 compiler with canonical semantic back-edge routing.

    The core compiler owns deterministic contract construction. This facade keeps
    gap ownership aligned with the frozen N1-N10 contract: request/schema facts
    supplied by the verified runtime binding belong to N1, never N4. No violation
    is suppressed or downgraded; only the semantic target is normalized.
    """

    def compile(
        self,
        case_payload: Mapping[str, Any],
        data_ref_payloads: Sequence[Mapping[str, Any]],
        runtime_binding: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> ExecutableContract:
        try:
            return super().compile(
                case_payload,
                data_ref_payloads,
                runtime_binding,
                now=now,
            )
        except ExecutableReadinessError as error:
            rewritten = []
            changed = False
            for violation in error.violations:
                target_node = violation.target_node
                if violation.code in _RUNTIME_BINDING_VIOLATION_CODES:
                    target_node = "N1"
                if target_node != violation.target_node:
                    changed = True
                rewritten.append(
                    ReadinessViolation(
                        violation.code,
                        target_node,
                        violation.field,
                        violation.reason,
                    )
                )
            if changed:
                raise ExecutableReadinessError(tuple(rewritten)) from error
            raise


__all__ = [
    "ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT",
    "EVENT_N6_EXECUTABLE_CONTRACT_COMPILED",
    "N6_SCHEMA_VERSION",
    "ReadinessViolation",
    "ExecutableReadinessError",
    "ExecutableContract",
    "N6ExecutableReadinessCompiler",
]
