from __future__ import annotations

import unittest

from rc8_center.execution_admission import N7ExecutionAdmission, N7ExecutionAdmissionError
from rc8_center.n7_execution_result_receipt import DERIVED_RESULT_EVENT_TYPE, DERIVED_RESULT_PRODUCER_REF
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane
from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind


class _Control:
    def __init__(self):
        self.appended = 0

    def _require_active_lease(self, work_item_id, node_id, lease_id):
        return object()

    def stage_instance_id_for_work_item(self, work_item_id):
        return "stage-n7"

    def append_runtime_event(self, event, *, lease_id):
        self.appended += 1
        return {"status": "APPENDED"}


class _AdmissionGate:
    def __init__(self):
        self.admission = N7ExecutionAdmission(
            test_run_id="run-1",
            work_item_id="work-1",
            case_id="case-1",
            stage_instance_id="stage-n7",
            mission_node_id="n7-1",
            prepared_attempt_id="prepared-1",
            case_execution_attempt_id="case-attempt-1",
            executable_spec_id="spec-1",
            frozen_case_ref="case-revision-1",
            case_inventory_ref="artifact:inventory-1",
            case_inventory_fingerprint_ref="sha256:inventory",
            script_artifact_ref="artifact:bundle-1",
            driver_ref="driver:junit",
        )

    def authorize_start(self, *, work, stage_instance_id):
        return self.admission


class N7DerivedResultReceiptBoundaryTest(unittest.TestCase):
    def test_lease_holding_node_cannot_submit_center_derived_result_event(self):
        control = _Control()
        wrapped = N7AdmissionAwareFormalCenterControlPlane(control, _AdmissionGate())
        event = RuntimeEventEnvelope(
            event_id="worker-forged-derived-result",
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=RuntimeProducerKind.NODE_AGENT,
            producer_ref=DERIVED_RESULT_PRODUCER_REF,
            event_type=DERIVED_RESULT_EVENT_TYPE,
            sequence=1,
            case_id="case-1",
            attempt_id="case-attempt-1",
            refs=["artifact:ev-a"],
            data={"outcome": "PASS"},
            occurred_at=1,
        )
        with self.assertRaisesRegex(N7ExecutionAdmissionError, "CENTER_OWNS_N7_DERIVED_RESULT_RECEIPT"):
            wrapped.append_runtime_event(event, lease_id="lease-1")
        self.assertEqual(0, control.appended)


if __name__ == "__main__":
    unittest.main()
