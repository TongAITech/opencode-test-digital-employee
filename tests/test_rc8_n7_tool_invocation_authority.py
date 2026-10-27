from __future__ import annotations

import unittest
from types import SimpleNamespace

from rc8_center.execution_admission import N7ExecutionAdmission
from rc8_center.executable_readiness import ExecutableReadinessState
from rc8_center.n7_tool_invocation import (
    CenterN7ToolInvocationAuthority,
    N7ToolInvocationAuthorityError,
)


class _Coordination:
    def __init__(self) -> None:
        self.values = {}

    def key(self, lease_type: str, resource_id: str):
        return (lease_type, resource_id)

    def seed_work(self, work_item_id: str, *, owner_id: str = "node-1", lease_id: str = "lease-1", ttl: int = 120) -> None:
        self.values[self.key("work-item", work_item_id)] = {
            "owner_id": owner_id,
            "lease_id": lease_id,
            "ttl_seconds": ttl,
        }

    def lease_info(self, lease_type: str, resource_id: str):
        value = self.values.get(self.key(lease_type, resource_id))
        return dict(value) if value is not None else None

    def acquire_lease(self, lease_type: str, resource_id: str, owner_id: str, ttl_seconds: int, *, lease_id=None) -> bool:
        key = self.key(lease_type, resource_id)
        if key in self.values:
            return False
        self.values[key] = {
            "owner_id": owner_id,
            "lease_id": str(lease_id or ""),
            "ttl_seconds": int(ttl_seconds),
        }
        return True


class _Repository:
    def __init__(self, spec: object) -> None:
        self.spec = spec

    def get_executable_spec(self, executable_spec_id: str):
        if executable_spec_id == self.spec.executable_spec_id:
            return self.spec
        return None


class N7ToolInvocationAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.admission = N7ExecutionAdmission(
            test_run_id="run-1",
            work_item_id="work-n7",
            case_id="CASE-1",
            stage_instance_id="stage-n7",
            mission_node_id="run-1:scope:N7",
            prepared_attempt_id="prepared-1",
            case_execution_attempt_id="case-attempt-1",
            executable_spec_id="spec-1",
            frozen_case_ref="case-revision:CASE-1:v1",
            case_inventory_ref="artifact:inventory-1",
            case_inventory_fingerprint_ref="case-inventory-sha256:" + "a" * 64,
            script_artifact_ref="artifact:bundle-1",
            driver_ref="driver:maven-junit",
        )
        self.spec = SimpleNamespace(
            executable_spec_id="spec-1",
            test_run_id="run-1",
            case_id="CASE-1",
            attempt_id="case-attempt-1",
            prepared_attempt_id="prepared-1",
            frozen_case_ref="case-revision:CASE-1:v1",
            driver_ref="driver:maven-junit",
            evidence_collector_refs=("collector:junit",),
            state=ExecutableReadinessState.READY,
        )
        self.coordination = _Coordination()
        self.coordination.seed_work("work-n7")
        self.authority = CenterN7ToolInvocationAuthority(
            self.coordination,
            SimpleNamespace(repository=_Repository(self.spec)),
        )

    def test_issue_is_idempotent_and_binds_current_work_lease(self):
        first = self.authority.issue(self.admission, node_id="node-1", governance_lease_id="lease-1")
        second = self.authority.issue(self.admission, node_id="node-1", governance_lease_id="lease-1")
        self.assertTrue(first.token)
        self.assertEqual(first.token, second.token)
        self.assertEqual(first.resource_id, second.resource_id)
        self.assertGreater(first.ttl_seconds, 0)

    def test_driver_and_collector_require_and_accept_grant(self):
        grant = self.authority.issue(self.admission, node_id="node-1", governance_lease_id="lease-1")
        for producer in ("driver:maven-junit", "collector:junit"):
            self.assertTrue(self.authority.producer_requires_grant(self.admission, producer))
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token=grant.token,
                producer_ref=producer,
                case_id="CASE-1",
                case_execution_attempt_id="case-attempt-1",
            )
        self.assertFalse(self.authority.producer_requires_grant(self.admission, "runtime-reality-probe"))

    def test_worker_cannot_forge_result_tool_with_only_work_lease(self):
        with self.assertRaisesRegex(N7ToolInvocationAuthorityError, "N7_RESULT_TOOL_INVOCATION_AUTHORITY_REQUIRED"):
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token="",
                producer_ref="driver:maven-junit",
                case_id="CASE-1",
                case_execution_attempt_id="case-attempt-1",
            )

    def test_wrong_token_producer_or_attempt_is_rejected(self):
        grant = self.authority.issue(self.admission, node_id="node-1", governance_lease_id="lease-1")
        with self.assertRaisesRegex(N7ToolInvocationAuthorityError, "N7_TOOL_INVOCATION_TOKEN_MISMATCH"):
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token="wrong-token",
                producer_ref="driver:maven-junit",
                case_id="CASE-1",
                case_execution_attempt_id="case-attempt-1",
            )
        with self.assertRaisesRegex(N7ToolInvocationAuthorityError, "N7_TOOL_INVOCATION_PRODUCER_NOT_AUTHORIZED"):
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token=grant.token,
                producer_ref="worker:fake-tool",
                case_id="CASE-1",
                case_execution_attempt_id="case-attempt-1",
            )
        with self.assertRaisesRegex(N7ToolInvocationAuthorityError, "N7_TOOL_INVOCATION_ATTEMPT_MISMATCH"):
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token=grant.token,
                producer_ref="driver:maven-junit",
                case_id="CASE-1",
                case_execution_attempt_id="old-attempt",
            )

    def test_stale_or_reacquired_work_lease_invalidates_grant(self):
        grant = self.authority.issue(self.admission, node_id="node-1", governance_lease_id="lease-1")
        self.coordination.seed_work("work-n7", owner_id="node-1", lease_id="lease-2", ttl=120)
        with self.assertRaisesRegex(N7ToolInvocationAuthorityError, "N7_TOOL_INVOCATION_WORK_LEASE_STALE"):
            self.authority.authorize(
                self.admission,
                node_id="node-1",
                governance_lease_id="lease-1",
                token=grant.token,
                producer_ref="driver:maven-junit",
                case_id="CASE-1",
                case_execution_attempt_id="case-attempt-1",
            )


if __name__ == "__main__":
    unittest.main()
