import json
from pathlib import Path
from types import SimpleNamespace

import rc7_runtime.bank_execution_autopilot as execution_autopilot_module
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.case_runtime import CaseRuntimeError
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus


def test_preparation_runtime_failure_becomes_durable_block_before_business_execution(
    tmp_path: Path, monkeypatch
):
    mission_id = "M-EXEC-PREPARATION-RUNTIME-BLOCK"
    task_id = "T-EXEC-PREPARATION-RUNTIME-BLOCK"
    tc_id = "TC-PREPARATION-RUNTIME-BLOCK"
    worker_id = "worker-preparation-runtime"
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="R-EXEC-PREPARATION-RUNTIME-BLOCK",
            goal="fail closed when governed Case preparation runtime evidence cannot be produced",
        ),
    )
    control.register_task(
        Task(
            task_id=task_id,
            mission_id=mission_id,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute only after governed Case preparation succeeds",
            required_capabilities=["test_execution"],
        )
    )

    bundle = SimpleNamespace(
        spec=SimpleNamespace(layer="L3", case_version=1),
        frozen_case={"tc_id": tc_id},
    )

    class _BundleResolver:
        @staticmethod
        def resolve(*_args, **_kwargs):
            return bundle

    class _ExecutionService:
        def __init__(self):
            self.activate_calls = 0
            self.execute_calls = 0

        def activate_task(self, runtime_control, runtime_task_id, **_kwargs):
            self.activate_calls += 1
            leased = runtime_control.lease_next(
                worker_ref=worker_id,
                capabilities=("test_execution",),
            )
            assert leased is not None
            assert leased.task_id == runtime_task_id
            return SimpleNamespace(runtime_worker_id=worker_id)

        def execute_active_task(self, *_args, **_kwargs):
            self.execute_calls += 1
            raise AssertionError("business execution must not start after preparation runtime failure")

    class _FailingPreparationService:
        def __init__(self, *_args, **_kwargs):
            pass

        def prepare(self, **_kwargs):
            raise CaseRuntimeError(
                "CASE_PROVIDER_EXECUTION_FAILED:DATA_VERIFY:provider unavailable"
            )

    execution = _ExecutionService()
    monkeypatch.setattr(
        execution_autopilot_module,
        "CasePreparationService",
        _FailingPreparationService,
    )

    runtime = object.__new__(BankExecutionAutopilot)
    runtime.state_root = tmp_path / "state"
    runtime.evidence_root = tmp_path / "evidence"
    runtime.package_root = tmp_path
    runtime.target_id = "BANK-TARGET-1"
    runtime.authority = object()
    runtime.oracle = object()
    runtime.bundle_resolver = _BundleResolver()
    runtime.profiles = SimpleNamespace(
        get=lambda _layer: SimpleNamespace(required_tools=())
    )
    runtime._capability_broker = lambda _required_tools: object()
    runtime._case_for_task = lambda _control, _task: tc_id
    runtime.n8_upstream_successor = SimpleNamespace(
        authorize_if_ready=lambda *_args, **_kwargs: None,
        materialize_if_authorized=lambda *_args, **_kwargs: None,
    )
    runtime.n8_successor = SimpleNamespace(
        materialize_direct_successor=lambda *_args, **_kwargs: None,
    )
    runtime.execution = execution

    # Redline contract: provider/runtime evidence failures are operational
    # fail-closed conditions. The Task is already LEASED at this point, but no
    # business runner has started. The Driver must persist a blocker instead of
    # letting CaseRuntimeError escape and strand the Task in LEASED.
    runtime.run(control, control.scheduler.task(task_id))

    assert execution.activate_calls == 1
    assert execution.execute_calls == 0
    blocked = control.scheduler.task(task_id)
    assert blocked.state == TaskStatus.BLOCKED
    evaluations = truth.query("rc7_evaluation", evaluation_id=blocked.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["result"] == "BLOCKED"
    assert evaluations[0]["dimensions"]["status"] == "BLOCKED_PREPARATION_RUNTIME"
    assert evaluations[0]["dimensions"]["reason"] == (
        "EXECUTION_PREPARATION_RUNTIME_FAILED:"
        "CASE_PROVIDER_EXECUTION_FAILED:DATA_VERIFY:provider unavailable"
    )

    blocker_rows = [
        row
        for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == "RUNTIME_EXECUTION_BLOCKER"
    ]
    assert len(blocker_rows) == 1
    blocker_ref = str(blocker_rows[0]["content_ref"])
    assert blocker_ref.startswith("file://")
    blocker_payload = json.loads(
        Path(blocker_ref[len("file://"):]).read_text(encoding="utf-8")
    )
    assert blocker_payload["status"] == "BLOCKED_PREPARATION_RUNTIME"
    assert blocker_payload["details"]["phase"] == "CASE_PREPARATION"
    assert blocker_payload["details"]["business_action_executed"] is False
    assert truth.query("execution_attempt") == []

    mission_rows = truth.query("rc7_mission", mission_id=mission_id)
    assert len(mission_rows) == 1
    assert mission_rows[0]["state"] == "BLOCKED"
