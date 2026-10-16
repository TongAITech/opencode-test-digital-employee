from __future__ import annotations

from rc7_runtime.mission_graph import MissionTaskGraphCompiler


def test_generic_compiler_default_remains_legacy_v1() -> None:
    compiler = MissionTaskGraphCompiler()
    assert compiler.graph_version == "v1"
    assert compiler.NODE_ORDER == (
        "REQUIREMENT_ANALYSIS",
        "CODE_ANALYSIS",
        "TEST_DESIGN",
        "SCRIPT_READINESS",
        "EXECUTION",
    )


def test_v2_is_responsibility_graph_not_flat_ai_worker_chain() -> None:
    compiler = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V2)
    graph = compiler.compile("MISSION-V2-OWNERSHIP")

    assert compiler.NODE_ORDER == (
        "REALITY_RECON",
        "REQUIREMENT_ANALYSIS",
        "CODE_ANALYSIS",
        "TEST_DESIGN",
        "SCRIPT_READINESS",
        "EXECUTION",
    )
    assert len(graph.tasks) == 6
    assert "PRECONDITION_DATA" not in compiler.NODE_ORDER
    assert "REPORT" not in compiler.NODE_ORDER

    assert compiler.task_owner("REALITY_RECON") == compiler.OWNER_RUNTIME
    assert graph.task("REALITY_RECON").task_type == "RUNTIME"
    for node in ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN", "SCRIPT_READINESS", "EXECUTION"):
        assert compiler.task_owner(node) == compiler.OWNER_PRODUCER
        assert graph.task(node).task_type == "PRODUCE"

    assert graph.stage_ownership["REQUIREMENT_SUFFICIENCY"] == compiler.OWNER_AUTHORITY
    assert graph.stage_ownership["CODE_SUFFICIENCY"] == compiler.OWNER_AUTHORITY
    assert graph.stage_ownership["TEST_DESIGN_SUFFICIENCY"] == compiler.OWNER_AUTHORITY
    assert graph.stage_ownership["MISSION_CONVERGENCE"] == compiler.OWNER_AUTHORITY

    assert graph.runtime_substages == (
        "PRECONDITIONS",
        "TEST_DATA_PREPARATION",
        "ACTUAL_RESULT",
        "ORACLE",
    )
    for stage in graph.runtime_substages:
        assert graph.stage_ownership[stage] == compiler.OWNER_RUNTIME

    assert graph.conditional_stages == ("FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW")
    for stage in graph.conditional_stages:
        assert graph.stage_ownership[stage] == compiler.OWNER_CONDITIONAL_RUNTIME

    assert graph.post_convergence_stages == ("FINAL_REPORT",)
    assert graph.stage_ownership["FINAL_REPORT"] == compiler.OWNER_POST_CONVERGENCE
    assert graph.logical_stages.index("MISSION_CONVERGENCE") < graph.logical_stages.index("FINAL_REPORT")


def test_v2_execution_contract_keeps_runtime_preparation_and_oracle_out_of_free_workers() -> None:
    compiler = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V2)
    execution = compiler.compile("MISSION-V2-EXECUTION").task("EXECUTION")

    criteria = "\n".join(execution.acceptance_criteria)
    assert "per-case/per-attempt preconditions and test data are prepared by Runtime" in criteria
    assert "database writes require Human Gate authorization" in criteria
    assert "actual result capture and deterministic oracle are Runtime-owned" in criteria


def test_v2_contract_hash_covers_ownership_and_post_convergence_boundary() -> None:
    compiler = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V2)
    contract = compiler.contract()

    assert contract["graph_version"] == "v2"
    assert contract["task_ownership"]["REALITY_RECON"] == "RUNTIME"
    assert contract["stage_ownership"]["FINAL_REPORT"] == "POST_CONVERGENCE"
    assert contract["runtime_substages"] == ["PRECONDITIONS", "TEST_DATA_PREPARATION", "ACTUAL_RESULT", "ORACLE"]
    assert contract["post_convergence_stages"] == ["FINAL_REPORT"]
    assert len(contract["contract_sha256"]) == 64
