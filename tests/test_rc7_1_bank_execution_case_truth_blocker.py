import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus


def test_case_truth_resolution_failure_becomes_durable_block_before_case_execution(tmp_path: Path):
    mission_id = "M-EXEC-CASE-TRUTH-BLOCK"
    execution_task_id = "T-EXEC-CASE-TRUTH-BLOCK"
    truth = TruthRuntime(tmp_path / "case-truth-r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="R-EXEC-CASE-TRUTH-BLOCK",
            goal="fail closed when canonical accepted Case truth is ambiguous",
        ),
    )

    # Authentic R1 drift: two canonical TEST_DESIGN/PRODUCE tasks make the
    # accepted Case denominator non-unique. AcceptedCaseInventoryReader.load()
    # must raise TEST_DESIGN_TASK_NOT_UNIQUE on the real runtime path.
    control.register_task(
        Task(
            task_id="T-DESIGN-A",
            mission_id=mission_id,
            node="TEST_DESIGN",
            task_type="PRODUCE",
            objective="first conflicting accepted design owner",
            required_capabilities=["test_design"],
        )
    )
    control.register_task(
        Task(
            task_id="T-DESIGN-B",
            mission_id=mission_id,
            node="TEST_DESIGN",
            task_type="PRODUCE",
            objective="second conflicting accepted design owner",
            required_capabilities=["test_design"],
        )
    )
    control.register_task(
        Task(
            task_id=execution_task_id,
            mission_id=mission_id,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute only after accepted Case truth is uniquely resolved",
            required_capabilities=["test_execution"],
        )
    )

    runtime = BankExecutionAutopilot(
        authority=RC7AuthorityRuntime(b"0123456789abcdef-rc71-case-truth-key"),
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "evidence"),
        package_root=str(tmp_path),
        target_id="BANK-TARGET-1",
        capability_snapshot=None,
        timeout_seconds=30,
    )

    # Runtime truth damage is an operational fail-closed boundary, not a
    # programmer exception. The Driver must not receive a stack-only
    # CaseFanoutConformanceError and no business action may start.
    runtime.run(control, control.scheduler.task(execution_task_id))

    blocked = control.scheduler.task(execution_task_id)
    assert blocked.state == TaskStatus.BLOCKED
    evaluations = truth.query("rc7_evaluation", evaluation_id=blocked.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["result"] == "BLOCKED"
    assert evaluations[0]["dimensions"]["status"] == "BLOCKED_CASE_TRUTH"
    assert evaluations[0]["dimensions"]["reason"] == (
        "EXECUTION_CASE_TRUTH_RESOLUTION_FAILED:TEST_DESIGN_TASK_NOT_UNIQUE"
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
    blocker_payload = json.loads(
        Path(blocker_ref[len("file://"):]).read_text(encoding="utf-8")
    )
    assert blocker_payload["tc_id"] == "CASE_TRUTH_UNRESOLVED"
    assert blocker_payload["status"] == "BLOCKED_CASE_TRUTH"
    assert blocker_payload["details"]["phase"] == "CASE_TRUTH_RESOLUTION"
    assert blocker_payload["details"]["business_action_executed"] is False
    assert truth.query("execution_attempt") == []
