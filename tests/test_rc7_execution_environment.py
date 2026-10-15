from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.diagnosis import CorrelationScope
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_environment import (
    DiagnosisTrustProbeResult,
    ExecutionEnvironmentAdapter,
    ExecutionEnvironmentAdmissionService,
    ExecutionEnvironmentError,
    ToolProbeResult,
)
from rc7_runtime.models import Mission, Task, TaskStatus


MISSION = "MISSION-ENV-ADMIT"
TASK = "TASK-ENV-ADMIT"
TARGET = "TARGET-ENV-ADMIT"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-ENV-ADMIT",
            goal="prove executable environment admission",
        ),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute against admitted target",
            required_capabilities=["test_execution"],
        )
    )
    assert control.scheduler.task(TASK).state == TaskStatus.READY
    return truth, control


class LocalAdapter(ExecutionEnvironmentAdapter):
    def __init__(self, root: Path, *, broken=False):
        self.root = root
        self.broken = broken
        self.probed = []

    @property
    def adapter_id(self):
        return "local-real-probe-adapter"

    def probe_tool(self, *, tool_id, target_id, layer):
        self.probed.append((tool_id, target_id, layer))
        evidence = self.root / ("probe-%s.txt" % tool_id)
        evidence.write_text("real probe %s %s %s\n" % (tool_id, target_id, layer), encoding="utf-8")
        return ToolProbeResult(
            tool_id=tool_id,
            success=True,
            locator_ref="adapter-locator://%s" % tool_id,
            executable_ref="adapter-executable://%s" % tool_id,
            registration_ref="adapter-registration://%s" % tool_id,
            tool_call_ref=None if self.broken else "adapter-call://%s" % tool_id,
            evidence_ref="file://" + str(evidence),
            target_readiness_ref="adapter-target-ready://%s/%s" % (tool_id, target_id),
        )

    def resolve_precondition(self, spec, context):
        return {
            "success": True,
            "evidence_ref": "adapter-evidence://precondition/%s" % spec["id"],
        }

    def prepare_data(self, requirement, context, *, strategy):
        return {
            "success": True,
            "binding": {"strategy": strategy, "id": requirement["id"]},
            "tool_call_ref": "adapter-call://prepare/%s/%s" % (strategy, requirement["id"]),
            "evidence_ref": "adapter-evidence://prepare/%s/%s" % (strategy, requirement["id"]),
        }

    def verify_data(self, requirement, binding, context):
        return {
            "success": True,
            "evidence_ref": "adapter-evidence://verify/%s" % requirement["id"],
        }

    def execution_env(self, *, target_id, layer):
        return {"SECRET_SESSION_TOKEN": "must-never-be-persisted"}


class TrustedAdapter(LocalAdapter):
    def diagnosis_trust(self, *, target_id, layer):
        return DiagnosisTrustProbeResult(
            auth_verified=True,
            auth_evidence_ref="evidence://trust/auth",
            route_verified=True,
            route_evidence_ref="evidence://trust/route",
            environment_verified=True,
            environment_evidence_ref="evidence://trust/environment",
            dependency_verified=True,
            dependency_evidence_ref="evidence://trust/dependency",
            remote_integration=True,
            correlation=CorrelationScope(
                applications=("cfg-data",),
                window_start=100,
                window_end=200,
                request_id="REQ-TRUST-1",
            ),
        )

    def query_cat(self, scope, context):
        return {
            "tool_call_ref": "cat-call://%s" % scope.request_id,
            "evidence_ref": "cat-evidence://%s" % scope.request_id,
            "signals": {},
        }


class BrokenTrustAdapter(LocalAdapter):
    def diagnosis_trust(self, *, target_id, layer):
        return DiagnosisTrustProbeResult(auth_verified=True, auth_evidence_ref=None)


def test_l2_environment_admission_probes_database_and_persists_non_secret_truth(tmp_path: Path):
    truth, control = _control(tmp_path)
    adapter = LocalAdapter(tmp_path)
    admission = ExecutionEnvironmentAdmissionService(
        evidence_root=str(tmp_path / "evidence")
    ).admit(
        control,
        TASK,
        adapter=adapter,
        target_id=TARGET,
        layer="L2",
    )

    assert admission.required_tools == ("database",)
    assert admission.diagnostic_tools == ()
    assert adapter.probed == [("database", TARGET, "L2")]
    probe = admission.probe_results[0]
    assert probe.success is True
    assert probe.tool_call_ref == "adapter-call://database"
    assert len(truth.query("rc7_artifact", artifact_id=admission.artifact_id)) == 1
    evidence_rows = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in admission.evidence_ids
    ]
    assert {row["kind"] for row in evidence_rows} == {
        "EXECUTION_TOOL_PROBE",
        "EXECUTION_ENVIRONMENT_ADMISSION",
    }

    admission_path = Path(admission.content_ref[len("file://"):])
    persisted = admission_path.read_text(encoding="utf-8")
    assert "must-never-be-persisted" not in persisted
    assert "SECRET_SESSION_TOKEN" not in persisted
    assert "must-never-be-persisted" not in (tmp_path / "r1.jsonl").read_text(encoding="utf-8")

    admission.broker.bind_worker("database", "worker-1", visible=True, permitted=True)
    assert admission.broker.admit("worker-1", ["database"], TARGET).ready is True


def test_l3_environment_admission_requires_parent_api_runtime_and_cat(tmp_path: Path):
    _, control = _control(tmp_path)
    adapter = LocalAdapter(tmp_path)
    admission = ExecutionEnvironmentAdmissionService(
        evidence_root=str(tmp_path / "evidence")
    ).admit(
        control,
        TASK,
        adapter=adapter,
        target_id=TARGET,
        layer="L3",
    )
    assert admission.required_tools == ("api-runtime",)
    assert admission.diagnostic_tools == ("cat",)
    assert adapter.probed == [
        ("api-runtime", TARGET, "L3"),
        ("cat", TARGET, "L3"),
    ]


def test_evidence_backed_trust_is_persisted_and_compiled_for_diagnosis(tmp_path: Path):
    truth, control = _control(tmp_path)
    admission = ExecutionEnvironmentAdmissionService(
        evidence_root=str(tmp_path / "evidence")
    ).admit(
        control,
        TASK,
        adapter=TrustedAdapter(tmp_path),
        target_id=TARGET,
        layer="L3",
    )
    trust = admission.diagnosis_trust
    assert trust.auth_verified is True
    assert trust.route_verified is True
    assert trust.tool_verified is True
    assert trust.environment_verified is True
    assert trust.dependency_verified is True
    assert trust.remote_integration is True
    assert trust.correlation is not None
    rows = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in admission.evidence_ids
    ]
    trust_rows = [row for row in rows if row["kind"] == "EXECUTION_DIAGNOSIS_TRUST_EVIDENCE"]
    assert len(trust_rows) == 4
    persisted = Path(admission.content_ref[len("file://"):]).read_text(encoding="utf-8")
    assert "REQ-TRUST-1" not in persisted


def test_trust_boolean_without_evidence_is_rejected(tmp_path: Path):
    _, control = _control(tmp_path)
    with pytest.raises(
        ExecutionEnvironmentError,
        match="EXECUTION_ENVIRONMENT_TRUST_EVIDENCE_REQUIRED:auth",
    ):
        ExecutionEnvironmentAdmissionService(
            evidence_root=str(tmp_path / "evidence")
        ).admit(
            control,
            TASK,
            adapter=BrokenTrustAdapter(tmp_path),
            target_id=TARGET,
            layer="L2",
        )


def test_successful_probe_without_real_call_evidence_is_rejected(tmp_path: Path):
    _, control = _control(tmp_path)
    with pytest.raises(
        ExecutionEnvironmentError,
        match="EXECUTION_ENVIRONMENT_REAL_PROBE_EVIDENCE_REQUIRED:database:tool_call_ref",
    ):
        ExecutionEnvironmentAdmissionService(
            evidence_root=str(tmp_path / "evidence")
        ).admit(
            control,
            TASK,
            adapter=LocalAdapter(tmp_path, broken=True),
            target_id=TARGET,
            layer="L2",
        )


def test_adapter_is_compiled_into_preparation_callbacks_from_case_contract(tmp_path: Path):
    adapter = LocalAdapter(tmp_path)
    case = {
        "preconditions": [{"id": "PRE-AUTH", "type": "AUTH"}],
        "test_data": {
            "initial_state": [
                {"id": "STATE-1", "allowed_strategies": ["REUSE_EXISTING", "API_CREATE"]}
            ],
            "input_data": [
                {"id": "INPUT-1", "allowed_strategies": ["DERIVE"]}
            ],
        },
    }
    preconditions, strategies, verifier, human_gate = (
        ExecutionEnvironmentAdmissionService.preparation_callbacks(adapter, case)
    )
    assert set(preconditions) == {"AUTH"}
    assert set(strategies) == {"REUSE_EXISTING", "API_CREATE", "DERIVE"}
    assert preconditions["AUTH"](
        {"id": "PRE-AUTH"}, {"attempt_id": "ATT-1"}
    )["success"] is True
    assert strategies["API_CREATE"](
        {"id": "STATE-1"}, {"attempt_id": "ATT-1"}
    )["binding"]["strategy"] == "API_CREATE"
    assert verifier(
        {"id": "STATE-1"}, {"id": "X"}, {"attempt_id": "ATT-1"}
    )["success"] is True
    assert human_gate({"action": "DB_CREATE"}) is None
