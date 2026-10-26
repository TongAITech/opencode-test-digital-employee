import inspect
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.autonomous_n10_governed import GovernedAutonomousN10FinalizationService
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.bank_mission_autopilot import (
    BankMissionAutopilot,
    BankMissionAutopilotError,
    discover_config,
)
from rc7_runtime.case_script_bundle_resolver import CaseScriptBundleResolverError
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_capability import (
    ExecutionCapabilityBrokerFactory,
    ExecutionCapabilityEvidenceError,
)
from rc7_runtime.models import Mission, Task, TaskStatus


def _field_file(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_text(name, encoding="utf-8")
    return "file://" + str(path)


def test_execution_capability_snapshot_requires_real_probe_and_target_evidence(tmp_path: Path):
    target = "BANK-TARGET-1"
    snapshot = tmp_path / "execution-capabilities.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema": "pfc.aitest.rc7.1.execution-capabilities.v1",
                "target_id": target,
                "tools": {
                    "maven": {
                        "locator": "package://maven/bin/mvn",
                        "executable_ref": _field_file(tmp_path, "maven-executable.txt"),
                        "registration_ref": _field_file(tmp_path, "maven-registration.txt"),
                        "probe": {
                            "success": True,
                            "tool_call_ref": _field_file(tmp_path, "maven-probe-call.txt"),
                            "evidence_ref": _field_file(tmp_path, "maven-probe-evidence.txt"),
                        },
                        "target_readiness_ref": _field_file(tmp_path, "maven-target-ready.txt"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    broker = ExecutionCapabilityBrokerFactory(snapshot).build(
        target_id=target,
        required_tools=("maven",),
    )
    broker.bind_worker("maven", "worker-1", visible=True, permitted=True)
    readiness = broker.admit("worker-1", ("maven",), target)
    assert readiness.ready is True
    assert readiness.blocked == {}


def test_execution_capability_snapshot_does_not_invent_missing_tool(tmp_path: Path):
    snapshot = tmp_path / "execution-capabilities.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema": "pfc.aitest.rc7.1.execution-capabilities.v1",
                "target_id": "BANK-TARGET-1",
                "tools": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ExecutionCapabilityEvidenceError, match="EXECUTION_CAPABILITY_TOOL_MISSING:maven"):
        ExecutionCapabilityBrokerFactory(snapshot).build(
            target_id="BANK-TARGET-1",
            required_tools=("maven",),
        )


def _autopilot_package(tmp_path: Path):
    root = tmp_path / "package"
    (root / "runtime-state" / "r1").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "SOURCE_COMMIT").write_text("0123456789abcdef", encoding="utf-8")
    (root / "state" / "rc7-dsh-runtime-profile.json").write_text(
        json.dumps({"runtime_profile": "rc7-bank"}), encoding="utf-8"
    )
    (root / "state" / "rc7-dsh.patch.yml").write_text("patch: true\n", encoding="utf-8")
    dsh = root / "dsh"
    dsh.write_text("stub", encoding="utf-8")
    return root, dsh


def test_autopilot_config_uses_explicit_or_runtime_owned_run_identity(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("PFC_RC7_AUTONOMOUS_RUN_ID", raising=False)
    root, dsh = _autopilot_package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    config = discover_config(
        r1_path=str(r1),
        mission_id="M-AUTO-1",
        release_id="R-AUTO-1",
        goal="autonomous bank mission",
        run_id="RUN-AUTO-1",
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
    )
    assert config.target_id == "BANK-TARGET-1"
    assert config.run_id == "RUN-AUTO-1"
    assert config.runtime_profile == "rc7-bank"
    assert config.execution_capability_snapshot is None

    start_or_resume(
        r1_path=str(r1),
        mission_id="M-AUTO-1",
        release_id="R-AUTO-1",
        goal="autonomous bank mission",
    )
    autopilot = BankMissionAutopilot(config)
    assert isinstance(autopilot.n10, GovernedAutonomousN10FinalizationService)

    with pytest.raises(BankMissionAutopilotError, match="AUTOPILOT_TARGET_ID_REQUIRED_NO_GUESSING"):
        discover_config(
            r1_path=str(r1),
            mission_id="M-AUTO-2",
            release_id="R-AUTO-1",
            goal="autonomous bank mission",
            run_id="RUN-AUTO-2",
            package_root=str(root),
            dsh_bin=str(dsh),
            target_id=None,
        )

    derived_a = discover_config(
        r1_path=str(r1),
        mission_id="M-DERIVED",
        release_id="R-AUTO-1",
        goal="autonomous bank mission",
        run_id=None,
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
    )
    derived_b = discover_config(
        r1_path=str(r1),
        mission_id="M-DERIVED",
        release_id="R-AUTO-1",
        goal="autonomous bank mission",
        run_id=None,
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
    )
    different = discover_config(
        r1_path=str(r1),
        mission_id="M-DERIVED-OTHER",
        release_id="R-AUTO-1",
        goal="autonomous bank mission",
        run_id=None,
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
    )
    assert derived_a.run_id.startswith("RUN-RC71-")
    assert derived_a.run_id == derived_b.run_id
    assert derived_a.run_id != different.run_id

    monkeypatch.setenv("PFC_RC7_AUTONOMOUS_RUN_ID", "RUN-ENV")
    with pytest.raises(BankMissionAutopilotError, match="AUTOPILOT_RUN_ID_CLI_ENV_CONFLICT"):
        discover_config(
            r1_path=str(r1),
            mission_id="M-CONFLICT",
            release_id="R-AUTO-1",
            goal="autonomous bank mission",
            run_id="RUN-CLI",
            package_root=str(root),
            dsh_bin=str(dsh),
            target_id="BANK-TARGET-1",
        )


def test_missing_execution_capability_becomes_durable_block_not_fake_pass(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="M-EXEC-BLOCK",
            release_id="R-EXEC-BLOCK",
            goal="prove missing field capability blocks execution durably",
        ),
    )
    task = Task(
        task_id="T-EXEC-BLOCK",
        mission_id="M-EXEC-BLOCK",
        node="EXECUTION",
        task_type="EXECUTE",
        objective="execute accepted bank case",
        required_capabilities=["test_execution"],
    )
    control.register_task(task)
    runtime = BankExecutionAutopilot(
        authority=RC7AuthorityRuntime(b"0123456789abcdef-rc71-autopilot-key"),
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "evidence"),
        package_root=str(tmp_path),
        target_id="BANK-TARGET-1",
        capability_snapshot=None,
        timeout_seconds=30,
    )
    runtime._block(
        control,
        control.scheduler.task(task.task_id),
        worker_ref="rc7.1-execution-blocker",
        tc_id="TC-1",
        status="FIELD_REQUIRED",
        reason="EXECUTION_CAPABILITY_SNAPSHOT_REQUIRED",
    )
    blocked = control.scheduler.task(task.task_id)
    assert blocked.state == TaskStatus.BLOCKED
    evaluations = truth.query("rc7_evaluation", evaluation_id=blocked.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["result"] == "BLOCKED"
    assert evaluations[0]["dimensions"]["test_result"] == "BLOCKED"
    gaps = truth.query("rc7_gap", mission_id="M-EXEC-BLOCK")
    assert any(gap["category"] == "EXECUTION_BLOCKED" for gap in gaps)
    assert not any(row.get("result") == "PASS" for row in evaluations)


def test_script_bundle_resolution_failure_becomes_durable_block_before_business_execution(tmp_path: Path):
    mission_id = "M-EXEC-SCRIPT-BUNDLE-BLOCK"
    task_id = "T-EXEC-SCRIPT-BUNDLE-BLOCK"
    tc_id = "TC-SCRIPT-BUNDLE-BLOCK"
    truth = TruthRuntime(tmp_path / "script-bundle-r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="R-EXEC-SCRIPT-BUNDLE-BLOCK",
            goal="fail closed when the accepted Case script bundle cannot be rebuilt",
        ),
    )
    control.register_task(
        Task(
            task_id=task_id,
            mission_id=mission_id,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute accepted bank case only after runtime script-bundle verification",
            required_capabilities=["test_execution"],
        )
    )

    class _FailingBundleResolver:
        @staticmethod
        def resolve(*_args, **_kwargs):
            raise CaseScriptBundleResolverError(
                "CASE_SCRIPT_READY_RECEIPT_REQUIRED:%s" % tc_id
            )

    runtime = object.__new__(BankExecutionAutopilot)
    runtime.package_root = tmp_path
    runtime.evidence_root = tmp_path / "evidence"
    runtime.bundle_resolver = _FailingBundleResolver()
    runtime._case_for_task = lambda _control, _task: tc_id

    # This is a runtime field drift/preflight failure, not a programmer error.
    # The Driver must receive a durable BLOCKED boundary instead of a stack-only
    # CaseScriptBundleResolverError. No business execution is allowed to start.
    runtime.run(control, control.scheduler.task(task_id))

    blocked = control.scheduler.task(task_id)
    assert blocked.state == TaskStatus.BLOCKED
    evaluations = truth.query("rc7_evaluation", evaluation_id=blocked.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["result"] == "BLOCKED"
    assert evaluations[0]["dimensions"]["status"] == "BLOCKED_SCRIPT_BUNDLE"
    assert evaluations[0]["dimensions"]["reason"] == (
        "EXECUTION_SCRIPT_BUNDLE_RESOLUTION_FAILED:"
        "CASE_SCRIPT_READY_RECEIPT_REQUIRED:%s" % tc_id
    )
    mission_rows = truth.query("rc7_mission", mission_id=mission_id)
    assert len(mission_rows) == 1
    assert mission_rows[0]["state"] == "BLOCKED"

    blocker_rows = [
        row
        for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == "RUNTIME_EXECUTION_BLOCKER"
    ]
    assert len(blocker_rows) == 1
    blocker_ref = str(blocker_rows[0]["content_ref"])
    assert blocker_ref.startswith("file://")
    blocker_payload = json.loads(Path(blocker_ref[len("file://"):]).read_text(encoding="utf-8"))
    assert blocker_payload["status"] == "BLOCKED_SCRIPT_BUNDLE"
    assert blocker_payload["details"]["phase"] == "SCRIPT_BUNDLE_RESOLUTION"
    assert blocker_payload["details"]["business_action_executed"] is False
    assert truth.query("execution_attempt") == []


def test_script_eval_routes_pass_through_governed_n6_before_returning_to_driver():
    source = inspect.getsource(BankMissionAutopilot._script_eval)
    assert source.index("self.script_evaluator.evaluate_and_apply") < source.index(
        "self._reconcile_script_node"
    )

    reconcile = inspect.getsource(BankMissionAutopilot._reconcile_script_node)
    assert "current.state != TaskStatus.PASS" in reconcile
    assert "self.node_closure.reconcile_script_task" in reconcile
    assert "AUTOPILOT_AUTONOMOUS_NODE_CLOSURE_FAILED:N6" in reconcile
