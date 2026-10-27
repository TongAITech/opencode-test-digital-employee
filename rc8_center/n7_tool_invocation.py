"""Transient Center authority for N7 result-producing tool invocations.

A WorkItem lease proves that a node may write runtime observations.  It does
not prove that an ASSERTION_OBSERVED fact or its evidence really came from the
N6-authorized driver/evidence collector.  This service adds a second, short-
lived authorization token for only those result-authoritative tool writes.

The token lives in Redis because it is execution authorization, not runtime
truth.  Losing Redis therefore fails closed; PASS/FAIL truth still comes only
from canonical R1 plus durable Center state.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Tuple

from .executable_readiness import ExecutableReadinessState
from .execution_admission import N7ExecutionAdmission


class N7ToolInvocationAuthorityError(ValueError):
    pass


@dataclass(frozen=True)
class N7ToolInvocationGrant:
    token: str
    resource_id: str
    ttl_seconds: int


class CenterN7ToolInvocationAuthority:
    LEASE_TYPE = "n7-tool-invocation"

    def __init__(self, coordination: object, executable_readiness: object) -> None:
        self.coordination = coordination
        self.executable_readiness = executable_readiness

    def issue(
        self,
        admission: N7ExecutionAdmission,
        *,
        node_id: str,
        governance_lease_id: str,
    ) -> N7ToolInvocationGrant:
        self._require_work_lease(admission, node_id=node_id, governance_lease_id=governance_lease_id)
        self._result_producers(admission)
        resource_id = self._resource_id(admission, governance_lease_id)
        existing = self.coordination.lease_info(self.LEASE_TYPE, resource_id)
        if existing is not None:
            if str(existing.get("owner_id") or "") != str(node_id):
                raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_OWNER_MISMATCH")
            token = str(existing.get("lease_id") or "")
            ttl = int(existing.get("ttl_seconds") or 0)
            if not token or ttl <= 0:
                raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_GRANT_INVALID")
            return N7ToolInvocationGrant(token=token, resource_id=resource_id, ttl_seconds=ttl)

        active = self.coordination.lease_info("work-item", admission.work_item_id)
        ttl = int((active or {}).get("ttl_seconds") or 0)
        if ttl <= 0:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_WORK_LEASE_EXPIRED")
        token = secrets.token_urlsafe(32)
        created = self.coordination.acquire_lease(
            self.LEASE_TYPE,
            resource_id,
            str(node_id),
            ttl,
            lease_id=token,
        )
        if not created:
            # Another request may have won an idempotent race.  Re-read and
            # accept only the same owner/current authority; never overwrite.
            existing = self.coordination.lease_info(self.LEASE_TYPE, resource_id)
            if existing is None or str(existing.get("owner_id") or "") != str(node_id):
                raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_GRANT_CONFLICT")
            token = str(existing.get("lease_id") or "")
            ttl = int(existing.get("ttl_seconds") or 0)
            if not token or ttl <= 0:
                raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_GRANT_INVALID")
        return N7ToolInvocationGrant(token=token, resource_id=resource_id, ttl_seconds=ttl)

    def producer_requires_grant(self, admission: N7ExecutionAdmission, producer_ref: str) -> bool:
        return str(producer_ref or "").strip() in set(self._result_producers(admission))

    def authorize(
        self,
        admission: N7ExecutionAdmission,
        *,
        node_id: str,
        governance_lease_id: str,
        token: str,
        producer_ref: str,
        case_id: str,
        case_execution_attempt_id: str,
    ) -> None:
        self._require_work_lease(admission, node_id=node_id, governance_lease_id=governance_lease_id)
        if str(case_id or "") != admission.case_id:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_CASE_MISMATCH")
        if str(case_execution_attempt_id or "") != admission.case_execution_attempt_id:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_ATTEMPT_MISMATCH")
        if not self.producer_requires_grant(admission, producer_ref):
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_PRODUCER_NOT_AUTHORIZED")
        supplied = str(token or "").strip()
        if not supplied:
            raise N7ToolInvocationAuthorityError("N7_RESULT_TOOL_INVOCATION_AUTHORITY_REQUIRED")
        resource_id = self._resource_id(admission, governance_lease_id)
        current = self.coordination.lease_info(self.LEASE_TYPE, resource_id)
        if current is None:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_GRANT_NOT_FOUND")
        if str(current.get("owner_id") or "") != str(node_id):
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_OWNER_MISMATCH")
        expected = str(current.get("lease_id") or "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_TOKEN_MISMATCH")
        if int(current.get("ttl_seconds") or 0) <= 0:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_GRANT_EXPIRED")

    def _require_work_lease(
        self,
        admission: N7ExecutionAdmission,
        *,
        node_id: str,
        governance_lease_id: str,
    ) -> None:
        current = self.coordination.lease_info("work-item", admission.work_item_id)
        if current is None:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_WORK_LEASE_REQUIRED")
        if str(current.get("owner_id") or "") != str(node_id):
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_WORK_LEASE_OWNER_MISMATCH")
        if str(current.get("lease_id") or "") != str(governance_lease_id):
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_WORK_LEASE_STALE")
        if int(current.get("ttl_seconds") or 0) <= 0:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_WORK_LEASE_EXPIRED")

    def _result_producers(self, admission: N7ExecutionAdmission) -> Tuple[str, ...]:
        spec = self.executable_readiness.repository.get_executable_spec(admission.executable_spec_id)
        if spec is None:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_EXECUTABLE_SPEC_NOT_FOUND")
        if spec.state != ExecutableReadinessState.READY:
            raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_REQUIRES_EXECUTABLE_READY")
        checks = (
            ("TEST_RUN", getattr(spec, "test_run_id", None), admission.test_run_id),
            ("CASE", getattr(spec, "case_id", None), admission.case_id),
            ("ATTEMPT", getattr(spec, "attempt_id", None), admission.case_execution_attempt_id),
            ("PREPARED_ATTEMPT", getattr(spec, "prepared_attempt_id", None), admission.prepared_attempt_id),
            ("FROZEN_CASE", getattr(spec, "frozen_case_ref", None), admission.frozen_case_ref),
            ("DRIVER", getattr(spec, "driver_ref", None), admission.driver_ref),
        )
        for label, actual, expected in checks:
            if str(actual or "") != str(expected or ""):
                raise N7ToolInvocationAuthorityError("N7_TOOL_INVOCATION_%s_AUTHORITY_MISMATCH" % label)
        values = [str(spec.driver_ref)]
        for value in tuple(spec.evidence_collector_refs or ()):
            ref = str(value or "").strip()
            if ref and ref not in values:
                values.append(ref)
        return tuple(values)

    @staticmethod
    def _resource_id(admission: N7ExecutionAdmission, governance_lease_id: str) -> str:
        raw = "|".join((
            admission.test_run_id,
            admission.work_item_id,
            admission.case_id,
            admission.case_execution_attempt_id,
            admission.executable_spec_id,
            str(governance_lease_id),
        ))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
