from __future__ import annotations

from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge
from rc7_runtime.models import Gap, GapSeverity, Task


def _assignment(node):
    return SimpleNamespace(
        scope="task:TEST",
        allowed_tools=("filesystem", "git", "codegraph"),
        worker_instance_id="worker-contract-%s" % node.lower(),
    )


def _control(tmp_path, mission_id):
    truth = TruthRuntime(tmp_path / (mission_id + ".jsonl"))
    return ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=mission_id, release_id="RC7.1", goal="test worker contract"),
    )


def test_code_producer_prompt_requires_structured_impact_surfaces(tmp_path):
    control = _control(tmp_path, "MISSION-CONTRACT-CODE")
    bridge = DshTaskWorkerBridge(control, object())
    task = Task(
        task_id="TASK-CODE",
        mission_id=control.mission_id,
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective="analyze code impact",
        required_capabilities=["code_reasoning", "code_reality"],
    )

    prompt = bridge.compile_prompt(task, _assignment("CODE"))

    assert "RC7_1_SUFFICIENCY_CONTRACT=" in prompt
    assert '"impact_surfaces"' in prompt
    assert '"impact_dimension_exclusions"' in prompt
    assert '"CALL_GRAPH"' in prompt
    assert '"DATABASE"' in prompt
    assert "calling CodeGraph without materializing impact_surfaces" in prompt


def test_requirement_prompt_forbids_silent_empty_dimensions(tmp_path):
    control = _control(tmp_path, "MISSION-CONTRACT-REQ")
    bridge = DshTaskWorkerBridge(control, object())
    task = Task(
        task_id="TASK-REQ",
        mission_id=control.mission_id,
        node="REQUIREMENT_ANALYSIS",
        task_type="PRODUCE",
        objective="analyze requirements",
        required_capabilities=["requirement_reasoning"],
    )

    prompt = bridge.compile_prompt(task, _assignment("REQ"))

    assert '"dimension_exclusions_schema"' in prompt
    assert "silent empty semantic dimensions" in prompt
    assert '"negative_paths"' in prompt
    assert '"side_effects"' in prompt


def test_test_design_prompt_contains_depth_and_interaction_contract(tmp_path):
    control = _control(tmp_path, "MISSION-CONTRACT-DESIGN")
    bridge = DshTaskWorkerBridge(control, object())
    task = Task(
        task_id="TASK-DESIGN",
        mission_id=control.mission_id,
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="design sufficient tests",
        required_capabilities=["test_design"],
    )

    prompt = bridge.compile_prompt(task, _assignment("DESIGN"))

    assert "density, concentration, kind diversity, critical depth" in prompt
    assert "BUSINESS_RULE x BOUNDARY" in prompt
    assert "CODE_IMPACT x REGRESSION" in prompt
    assert "mega-cases" in prompt


def test_repair_prompt_projects_canonical_gap_facts_not_only_gap_id(tmp_path):
    control = _control(tmp_path, "MISSION-CONTRACT-REPAIR")
    gap = Gap(
        gap_id="GAP-DENSITY-1",
        mission_id=control.mission_id,
        source_node="TEST_DESIGN",
        category="TEST_CASE_DENSITY_INSUFFICIENT",
        severity=GapSeverity.HIGH,
        target_node="TEST_DESIGN",
        description="CASE_DENSITY_INSUFFICIENT:ALL:required=100:cases=20:min=25",
        subject_refs=["ART-DESIGN", "OBL-001", "OBL-100"],
        evidence_refs=["EVD-DESIGN"],
        acceptance_criteria=["minimum 25 focused Cases plus all other v2 gates"],
    )
    repair = control.gap_planner.plan(gap, priority=0)
    assert repair is not None
    bridge = DshTaskWorkerBridge(control, object())

    prompt = bridge.compile_prompt(repair, _assignment("DESIGN-REPAIR"))

    assert '"canonical_gap_context"' in prompt
    assert '"category": "TEST_CASE_DENSITY_INSUFFICIENT"' in prompt
    assert "required=100:cases=20:min=25" in prompt
    assert "OBL-001" in prompt
    assert "minimum 25 focused Cases" in prompt
    assert "independent evaluator must re-evaluate the source node" in prompt
