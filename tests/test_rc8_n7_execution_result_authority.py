from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rc8_center.executable_readiness import ExecutableReadinessState, ExecutableSpec
from rc8_center.execution_admission import N7ExecutionAdmission, N7ExecutionAdmissionError
from rc8_center.n7_execution_result import (
    CenterN7CaseExecutionResultAuthority,
    N7CaseExecutionOutcome,
    N7CaseExecutionResult,
    N7CaseExecutionResultError,
)
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.contracts import ArtifactAvailability, RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger, runtime_event


class _SpecRepository:
    def __init__(self, spec):
        self.spec = spec

    def get_executable_spec(self, executable_spec_id):
        if executable_spec_id == self.spec.executable_spec_id:
            return self.spec
        return None


class _Readiness:
    def __init__(self, spec):
        self.repository = _SpecRepository(spec)


class _ArtifactRepository:
    def __init__(self):
        self.values = {}

    def get(self, artifact_id):
        return self.values.get(artifact_id)

    def put(self, value):
        self.values[value.artifact_id] = value


class _FakeControl:
    def __init__(self):
        self.completed = 0

    def _require_active_lease(self, work_item_id, node_id, lease_id):
        return object()

    def stage_instance_id_for_work_item(self, work_item_id):
        return "stage-n7"

    def complete_work_item(self, work_item_id, node_id, lease_id):
        self.completed += 1
        return {"work_item_id": work_item_id, "state": "COMPLETED"}


class _AdmissionGate:
    def __init__(self, admission):
        self.admission = admission

    def authorize_start(self, *, work, stage_instance_id):
        return self.admission


class _FixedResultAuthority:
    def __init__(self, result):
        self.result = result

    def evaluate(self, admission):
        return self.result


class N7ExecutionResultAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = CentralR1RuntimeLedger(
            str(Path(self.temp.name) / "event-stream.jsonl")
        )
        self.spec = ExecutableSpec(
            executable_spec_id="spec-1",
            test_run_id="run-1",
            mission_node_id="n6-1",
            case_id="case-1",
            attempt_id="case-attempt-1",
            prepared_attempt_id="prepared-1",
            frozen_case_ref="case-revision-1",
            driver_ref="driver:junit",
            script_artifact_ref="artifact:bundle-1",
            fixture_binding_refs=("fixture:1",),
            assertion_refs=("assertion:a", "assertion:b"),
            evidence_collector_refs=("collector:junit",),
            build_evidence_refs=("artifact:build-1",),
            semantic_evidence_refs=("artifact:semantic-1",),
            state=ExecutableReadinessState.READY,
            created_at=1,
            updated_at=2,
        )
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
        self.artifacts = _ArtifactRepository()
        self.authority = CenterN7CaseExecutionResultAuthority(
            runtime_ledger=self.ledger,
            executable_readiness=_Readiness(self.spec),
            artifact_repository=self.artifacts,
        )
        self.sequence = 0

    def tearDown(self):
        self.temp.cleanup()

    def _append(
        self,
        *,
        event_id,
        event_type="ASSERTION_OBSERVED",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="driver:junit",
        assertion_ref=None,
        outcome=None,
        evidence_refs=(),
        case_id="case-1",
        attempt_id="case-attempt-1",
    ):
        self.sequence += 1
        data = {}
        if assertion_ref is not None:
            data["assertion_ref"] = assertion_ref
        if outcome is not None:
            data["outcome"] = outcome
        if evidence_refs:
            data["evidence_refs"] = list(evidence_refs)
        event = runtime_event(
            event_id=event_id,
            test_run_id="run-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_kind=producer_kind,
            producer_ref=producer_ref,
            event_type=event_type,
            sequence=self.sequence,
            case_id=case_id,
            attempt_id=attempt_id,
            data=data,
        )
        self.ledger.append_runtime(event)

    def _artifact(
        self,
        artifact_id,
        assertion_ref,
        *,
        availability=ArtifactAvailability.AVAILABLE,
        attempt_id="case-attempt-1",
        case_id="case-1",
        work_item_id="work-1",
        node_id="node-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="collector:junit",
    ):
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id="run-1",
            work_item_id=work_item_id,
            node_id=node_id,
            kind="ASSERTION_EVIDENCE",
            producer_kind=producer_kind,
            producer_ref=producer_ref,
            file_name=artifact_id + ".json",
            sha256="a" * 64,
            size_bytes=1,
            availability=availability,
            case_id=case_id,
            attempt_id=attempt_id,
            step_id="step-" + assertion_ref.split(":")[-1],
            refs=[assertion_ref],
        )
        self.artifacts.put(manifest)
        return manifest

    def _result(self):
        return self.authority.evaluate(self.admission)

    def test_worker_pass_claim_and_worker_assertion_do_not_create_pass(self):
        self._append(
            event_id="event-worker-pass",
            event_type="CASE_EXECUTION_RESULT",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:n7",
            outcome="PASS",
        )
        self._append(
            event_id="event-worker-assertion",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="worker:n7",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a",),
        )
        result = self._result()
        self.assertEqual(N7CaseExecutionOutcome.PENDING, result.outcome)
        self.assertEqual((), result.resolved_assertion_refs)

    def test_partial_assertion_evidence_stays_pending(self):
        self._artifact("ev-a", "assertion:a")
        self._append(
            event_id="event-a",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a",),
        )
        result = self._result()
        self.assertEqual(N7CaseExecutionOutcome.PENDING, result.outcome)
        self.assertEqual(("assertion:a",), result.resolved_assertion_refs)

    def test_verified_failure_is_terminal_fail_without_waiting_for_other_assertions(self):
        self._artifact("ev-a", "assertion:a")
        self._append(
            event_id="event-a-fail",
            assertion_ref="assertion:a",
            outcome="FAIL",
            evidence_refs=("artifact:ev-a",),
        )
        result = self._result()
        self.assertEqual(N7CaseExecutionOutcome.FAIL, result.outcome)
        self.assertIn("assertion:a", result.reason)

    def test_all_required_verified_assertions_are_center_derived_pass(self):
        self._artifact("ev-a", "assertion:a")
        self._artifact("ev-b", "assertion:b")
        self._append(
            event_id="event-a-pass",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a",),
        )
        self._append(
            event_id="event-b-pass",
            assertion_ref="assertion:b",
            outcome="PASS",
            evidence_refs=("artifact:ev-b",),
        )
        result = self._result()
        self.assertEqual(N7CaseExecutionOutcome.PASS, result.outcome)
        self.assertEqual(("assertion:a", "assertion:b"), result.resolved_assertion_refs)
        self.assertEqual(("ev-a", "ev-b"), result.evidence_refs)

    def test_unavailable_evidence_cannot_create_pass(self):
        self._artifact(
            "ev-a",
            "assertion:a",
            availability=ArtifactAvailability.PENDING_UPLOAD,
        )
        self._artifact("ev-b", "assertion:b")
        self._append(
            event_id="event-a",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a",),
        )
        self._append(
            event_id="event-b",
            assertion_ref="assertion:b",
            outcome="PASS",
            evidence_refs=("artifact:ev-b",),
        )
        self.assertEqual(N7CaseExecutionOutcome.PENDING, self._result().outcome)

    def test_stale_attempt_evidence_is_rejected(self):
        self._artifact("ev-a", "assertion:a", attempt_id="old-attempt")
        self._append(
            event_id="event-a",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a",),
        )
        with self.assertRaisesRegex(
            N7CaseExecutionResultError,
            "N7_CASE_EXECUTION_EVIDENCE_ATTEMPT_MISMATCH",
        ):
            self._result()

    def test_unknown_assertion_from_authorized_tool_is_rejected(self):
        self._artifact("ev-x", "assertion:x")
        self._append(
            event_id="event-x",
            assertion_ref="assertion:x",
            outcome="PASS",
            evidence_refs=("artifact:ev-x",),
        )
        with self.assertRaisesRegex(
            N7CaseExecutionResultError,
            "N7_ASSERTION_NOT_IN_EXECUTABLE_SPEC",
        ):
            self._result()

    def test_conflicting_observations_are_rejected(self):
        self._artifact("ev-a-pass", "assertion:a")
        self._artifact("ev-a-fail", "assertion:a")
        self._append(
            event_id="event-a-pass",
            assertion_ref="assertion:a",
            outcome="PASS",
            evidence_refs=("artifact:ev-a-pass",),
        )
        self._append(
            event_id="event-a-fail",
            assertion_ref="assertion:a",
            outcome="FAIL",
            evidence_refs=("artifact:ev-a-fail",),
        )
        with self.assertRaisesRegex(
            N7CaseExecutionResultError,
            "N7_ASSERTION_OUTCOME_CONFLICT",
        ):
            self._result()

    def test_n7_completion_is_blocked_while_result_pending(self):
        pending = N7CaseExecutionResult(
            outcome=N7CaseExecutionOutcome.PENDING,
            test_run_id="run-1",
            work_item_id="work-1",
            case_id="case-1",
            case_execution_attempt_id="case-attempt-1",
            prepared_attempt_id="prepared-1",
            executable_spec_id="spec-1",
            assertion_refs=("assertion:a", "assertion:b"),
            resolved_assertion_refs=(),
            evidence_refs=(),
            reason="ASSERTION_EVIDENCE_PENDING",
        )
        control = _FakeControl()
        wrapped = N7AdmissionAwareFormalCenterControlPlane(
            control,
            _AdmissionGate(self.admission),
            _FixedResultAuthority(pending),
        )
        with self.assertRaisesRegex(
            N7ExecutionAdmissionError,
            "N7_CASE_EXECUTION_RESULT_PENDING",
        ):
            wrapped.complete_work_item("work-1", "node-1", "lease-1")
        self.assertEqual(0, control.completed)

    def test_n7_completion_accepts_terminal_pass_or_fail_but_does_not_relabel_it(self):
        for outcome in (N7CaseExecutionOutcome.PASS, N7CaseExecutionOutcome.FAIL):
            terminal = N7CaseExecutionResult(
                outcome=outcome,
                test_run_id="run-1",
                work_item_id="work-1",
                case_id="case-1",
                case_execution_attempt_id="case-attempt-1",
                prepared_attempt_id="prepared-1",
                executable_spec_id="spec-1",
                assertion_refs=("assertion:a", "assertion:b"),
                resolved_assertion_refs=("assertion:a", "assertion:b"),
                evidence_refs=("ev-a", "ev-b"),
                reason="TERMINAL",
            )
            control = _FakeControl()
            wrapped = N7AdmissionAwareFormalCenterControlPlane(
                control,
                _AdmissionGate(self.admission),
                _FixedResultAuthority(terminal),
            )
            result = wrapped.complete_work_item("work-1", "node-1", "lease-1")
            self.assertEqual("COMPLETED", result["state"])
            self.assertEqual(1, control.completed)


if __name__ == "__main__":
    unittest.main()
