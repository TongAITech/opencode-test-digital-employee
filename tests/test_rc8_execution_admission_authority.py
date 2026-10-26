from __future__ import annotations

import unittest
from types import SimpleNamespace

from rc8_center.execution_admission import N7ExecutionAdmission, N7ExecutionAdmissionError
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane


class _FixedAdmissionGate:
    def __init__(self, admission: N7ExecutionAdmission) -> None:
        self.admission = admission
        self.calls = []

    def authorize_start(self, *, work: object, stage_instance_id: str):
        self.calls.append((work, stage_instance_id))
        return self.admission


class _UnderlyingControl:
    def __init__(self) -> None:
        self.work = SimpleNamespace(identity=SimpleNamespace(work_item_id="work-n7"))
        self.events = []
        self.starts = []

    def _require_active_lease(self, work_item_id: str, node_id: str, lease_id: str):
        return self.work

    def stage_instance_id_for_work_item(self, work_item_id: str) -> str:
        return "stage-n7"

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        self.starts.append((work_item_id, node_id, lease_id))
        return {"state": "RUNNING"}

    def append_runtime_event(self, event: object, *, lease_id: str):
        self.events.append((event, lease_id))
        return {"accepted": True}


class N7RuntimeWriteAuthorityContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lease_id = "lease-n7-governance"
        self.admission = N7ExecutionAdmission(
            test_run_id="run-n7",
            work_item_id="work-n7",
            case_id="CASE-7",
            stage_instance_id="stage-n7",
            mission_node_id="mission-n7",
            prepared_attempt_id="prepared:case-attempt-7",
            case_execution_attempt_id="case-attempt-7",
            executable_spec_id="executable:case-attempt-7",
            frozen_case_ref="case-revision:CASE-7:v3",
            case_inventory_ref="artifact:case-inventory-7",
            case_inventory_fingerprint_ref="case-inventory-sha256:abc",
            script_artifact_ref="artifact:script-7",
            driver_ref="driver:maven-junit",
        )
        self.gate = _FixedAdmissionGate(self.admission)
        self.underlying = _UnderlyingControl()
        self.control = N7AdmissionAwareFormalCenterControlPlane(self.underlying, self.gate)

    def _event(
        self,
        *,
        event_type: str = "REALITY_CHANGED",
        test_run_id: str = "run-n7",
        work_item_id: str = "work-n7",
        case_id: str = "CASE-7",
        attempt_id: str = "case-attempt-7",
    ) -> object:
        return SimpleNamespace(
            event_id="event-1",
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id="node-n7",
            event_type=event_type,
            case_id=case_id,
            attempt_id=attempt_id,
        )

    def test_case_execution_event_uses_center_derived_case_attempt(self) -> None:
        result = self.control.append_runtime_event(self._event(), lease_id=self.lease_id)
        self.assertEqual({"accepted": True}, result)
        self.assertEqual(1, len(self.underlying.events))
        self.assertEqual(1, len(self.gate.calls))

    def test_worker_cannot_forge_case_identity(self) -> None:
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "N7_RUNTIME_EVENT_CASE_AUTHORITY_MISMATCH"):
            self.control.append_runtime_event(
                self._event(case_id="CASE-FORGED"),
                lease_id=self.lease_id,
            )
        self.assertEqual([], self.underlying.events)

    def test_worker_cannot_forge_case_execution_attempt_identity(self) -> None:
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "N7_RUNTIME_EVENT_ATTEMPT_AUTHORITY_MISMATCH"):
            self.control.append_runtime_event(
                self._event(attempt_id="case-attempt-forged"),
                lease_id=self.lease_id,
            )
        self.assertEqual([], self.underlying.events)

    def test_worker_cannot_forge_test_run_identity(self) -> None:
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "N7_RUNTIME_EVENT_TEST_RUN_AUTHORITY_MISMATCH"):
            self.control.append_runtime_event(
                self._event(test_run_id="run-forged"),
                lease_id=self.lease_id,
            )
        self.assertEqual([], self.underlying.events)

    def test_worker_cannot_forge_work_item_identity(self) -> None:
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "N7_RUNTIME_EVENT_WORK_ITEM_AUTHORITY_MISMATCH"):
            self.control.append_runtime_event(
                self._event(work_item_id="work-forged"),
                lease_id=self.lease_id,
            )
        self.assertEqual([], self.underlying.events)

    def test_terminal_attempt_event_uses_n7_governance_lease_attempt(self) -> None:
        result = self.control.append_runtime_event(
            self._event(event_type="ATTEMPT_COMPLETED", attempt_id=self.lease_id),
            lease_id=self.lease_id,
        )
        self.assertEqual({"accepted": True}, result)
        self.assertEqual(1, len(self.underlying.events))

    def test_terminal_attempt_event_rejects_case_execution_attempt(self) -> None:
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "N7_RUNTIME_EVENT_ATTEMPT_AUTHORITY_MISMATCH"):
            self.control.append_runtime_event(
                self._event(event_type="ATTEMPT_COMPLETED", attempt_id="case-attempt-7"),
                lease_id=self.lease_id,
            )
        self.assertEqual([], self.underlying.events)


if __name__ == "__main__":
    unittest.main()
