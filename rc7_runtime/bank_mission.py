"""Durable RC7 BANK Mission bootstrap/resume entrypoint.

New bank Missions default to graph v2. Existing Missions always resume the
graph identity already persisted in R1; pre-v2 field Missions are inferred as
v1 and are never silently upgraded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime
from .case_fanout_conformance import (
    contract_enabled as case_fanout_contract_enabled,
    persist_contract as persist_case_fanout_contract,
)
from .closed_loop_control import ClosedLoopControlPlane
from .execution_recovery_conformance import (
    contract_enabled as execution_recovery_contract_enabled,
    persist_contract as persist_execution_recovery_contract,
)
from .mission_graph import MissionTaskGraphCompiler
from .models import Evidence, Mission
from .node_tool_conformance import contract_enabled as node_tool_contract_enabled, persist_contract as persist_node_tool_contract
from .truth_overlay import append_entity


class BankMissionError(RuntimeError):
    pass


GRAPH_EVIDENCE_KIND = "MISSION_GRAPH_CONTRACT"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BankMissionError("%s_REQUIRED" % name.upper())
    return value.strip()


def _parse_inputs(values: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    grouped: Dict[str, list] = {}
    for raw in values:
        if not isinstance(raw, str) or "=" not in raw:
            raise BankMissionError("MISSION_INPUT_MUST_BE_NODE_EQUALS_REF")
        node, ref = raw.split("=", 1)
        node, ref = node.strip().upper(), ref.strip()
        if not node or not ref:
            raise BankMissionError("MISSION_INPUT_MUST_BE_NODE_EQUALS_REF")
        grouped.setdefault(node, []).append(ref)
    return {node: tuple(dict.fromkeys(refs)) for node, refs in grouped.items()}


def _mission_row(truth: TruthRuntime, mission_id: str):
    rows = truth.query("rc7_mission", mission_id=mission_id)
    if not rows:
        return None
    if len(rows) != 1:
        raise BankMissionError("MISSION_TRUTH_NOT_UNIQUE")
    return rows[0]


def _assert_resume_identity(row: Mapping[str, object], release_id: str, goal: str) -> None:
    if str(row.get("release_id") or "") != release_id:
        raise BankMissionError("MISSION_RELEASE_MISMATCH")
    if str(row.get("goal") or "") != goal:
        raise BankMissionError("MISSION_GOAL_MISMATCH")


def _graph_evidence_id(mission_id: str, version: str) -> str:
    return "EVD-GRAPH-" + hashlib.sha256((mission_id + "\x1f" + version).encode("utf-8")).hexdigest()[:20]


def _persist_graph_contract(truth, *, mission_id, release_id, compiler, task_ids) -> None:
    contract = compiler.contract()
    append_entity(
        truth,
        Evidence(
            evidence_id=_graph_evidence_id(mission_id, compiler.graph_version),
            mission_id=mission_id,
            kind=GRAPH_EVIDENCE_KIND,
            source_ref="runtime://mission-graph-compiler/%s" % compiler.graph_version,
            content_ref="mission-graph://%s/%s" % (compiler.graph_version, contract["contract_sha256"]),
            subject_refs=list(task_ids),
            content_hash=str(contract["contract_sha256"]),
        ),
        release_id=release_id,
        artifact_version=1,
    )


def _persisted_graph_version(truth: TruthRuntime, mission_id: str) -> Optional[str]:
    rows = [row for row in truth.query("rc7_evidence", mission_id=mission_id) if row.get("kind") == GRAPH_EVIDENCE_KIND]
    if len(rows) > 1:
        raise BankMissionError("MISSION_GRAPH_CONTRACT_NOT_UNIQUE")
    if rows:
        version = str(rows[0].get("source_ref") or "").rsplit("/", 1)[-1].strip().lower()
        if version not in MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS:
            raise BankMissionError("MISSION_GRAPH_VERSION_UNSUPPORTED:%s" % version)
        return version

    # Compatibility for Missions created before graph-version evidence existed.
    # Their persisted Task inventory is the authority; never upgrade them.
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    if not task_rows:
        return None
    nodes = {str(row.get("node") or "") for row in task_rows}
    if {"REALITY_RECON", "PRECONDITION_DATA", "REPORT"}.intersection(nodes):
        return MissionTaskGraphCompiler.GRAPH_V2
    if nodes.issubset(set(MissionTaskGraphCompiler.NODE_ORDER)):
        return MissionTaskGraphCompiler.GRAPH_V1
    raise BankMissionError("MISSION_GRAPH_VERSION_CANNOT_BE_INFERRED")


def _assert_resume_graph(truth, mission_id, external_inputs, compiler) -> None:
    expected = compiler.compile(mission_id, external_inputs=external_inputs)
    actual_rows = truth.query("rc7_task", mission_id=mission_id)
    actual = {str(row["task_id"]): row for row in actual_rows}
    if set(actual) != {task.task_id for task in expected.tasks}:
        raise BankMissionError("MISSION_GRAPH_IDENTITY_MISMATCH")
    for task in expected.tasks:
        row = actual[task.task_id]
        if list(row.get("dependency_task_ids", [])) != list(task.dependency_task_ids):
            raise BankMissionError("MISSION_GRAPH_DEPENDENCY_MISMATCH")
        if external_inputs and list(row.get("input_artifact_refs", [])) != list(task.input_artifact_refs):
            raise BankMissionError("MISSION_GRAPH_INPUT_MISMATCH")


def start_or_resume(*, r1_path: str, mission_id: str, release_id: str, goal: str,
                    external_inputs: Optional[Mapping[str, Sequence[str]]] = None,
                    graph_version: Optional[str] = None) -> Dict[str, object]:
    r1 = Path(_required(r1_path, "r1_path")).expanduser().resolve()
    mission_id, release_id, goal = _required(mission_id, "mission_id"), _required(release_id, "release_id"), _required(goal, "goal")
    r1.parent.mkdir(parents=True, exist_ok=True)
    inputs = dict(external_inputs or {})
    truth = TruthRuntime(r1)
    row = _mission_row(truth, mission_id)
    persisted = _persisted_graph_version(truth, mission_id)

    if row is None:
        selected = str(graph_version or MissionTaskGraphCompiler.BANK_DEFAULT_GRAPH_VERSION).lower()
        compiler = MissionTaskGraphCompiler(selected)
        control = ClosedLoopControlPlane.bootstrap(truth, Mission(mission_id=mission_id, release_id=release_id, goal=goal))
        graph = compiler.install(control, mission_id, external_inputs=inputs)
        task_ids = [task.task_id for task in graph.tasks]
        _persist_graph_contract(
            truth,
            mission_id=mission_id,
            release_id=release_id,
            compiler=compiler,
            task_ids=task_ids,
        )
        # New Bank graph-v2 Missions opt into durable node/tool, execution
        # recovery, and accepted-Case fan-out enforcement. Existing persisted
        # Missions are never silently upgraded on resume, preserving frozen
        # contract identity.
        if compiler.graph_version == MissionTaskGraphCompiler.GRAPH_V2:
            persist_node_tool_contract(
                truth,
                mission_id=mission_id,
                release_id=release_id,
                task_ids=task_ids,
            )
            script_tasks = [task for task in graph.tasks if task.node == "SCRIPT_READINESS"]
            execution_tasks = [task for task in graph.tasks if task.node == "EXECUTION"]
            if len(script_tasks) != 1:
                raise BankMissionError("V2_SCRIPT_TASK_NOT_UNIQUE")
            if len(execution_tasks) != 1:
                raise BankMissionError("V2_EXECUTION_TASK_NOT_UNIQUE")
            persist_execution_recovery_contract(
                truth,
                mission_id=mission_id,
                release_id=release_id,
                execution_task_id=execution_tasks[0].task_id,
            )
            persist_case_fanout_contract(
                truth,
                mission_id=mission_id,
                release_id=release_id,
                script_task_id=script_tasks[0].task_id,
                execution_task_id=execution_tasks[0].task_id,
            )
        action = "STARTED"
    else:
        _assert_resume_identity(row, release_id, goal)
        selected = persisted or MissionTaskGraphCompiler.GRAPH_V1
        if graph_version is not None and str(graph_version).lower() != selected:
            raise BankMissionError("MISSION_GRAPH_VERSION_MISMATCH")
        compiler = MissionTaskGraphCompiler(selected)
        _assert_resume_graph(truth, mission_id, inputs, compiler)
        control = ClosedLoopControlPlane(truth, release_id, mission_id)
        control.refresh_ready()
        action = "RESUMED"

    current = _mission_row(truth, mission_id)
    if current is None:
        raise BankMissionError("MISSION_TRUTH_MISSING_AFTER_START")
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    gap_rows = truth.query("rc7_gap", mission_id=mission_id)
    ready = sorted(({"task_id": str(x["task_id"]), "node": str(x["node"])} for x in task_rows if x.get("state") == "READY"),
                   key=lambda item: (item["node"], item["task_id"]))
    return {
        "status": action,
        "mission_id": mission_id,
        "release_id": release_id,
        "goal": goal,
        "graph_version": compiler.graph_version,
        "logical_stages": list(compiler.logical_stages),
        "stage_ownership": dict(compiler.stage_ownership),
        "runtime_substages": list(compiler.runtime_substages),
        "conditional_stages": list(compiler.conditional_stages),
        "post_convergence_stages": list(compiler.post_convergence_stages),
        "mission_state": str(current.get("state") or "UNKNOWN"),
        "sufficiency_state": str(current.get("sufficiency_state") or "UNKNOWN"),
        "r1_path": str(r1),
        "task_count": len(task_rows),
        "open_gap_count": len([x for x in gap_rows if x.get("state") in {"OPEN","PLANNED","REPAIRING","EVIDENCE_PENDING","HUMAN_REQUIRED","BLOCKED"}]),
        "ready_tasks": ready,
        "node_tool_contract_enabled": node_tool_contract_enabled(truth, mission_id),
        "execution_recovery_contract_enabled": execution_recovery_contract_enabled(truth, mission_id),
        "case_fanout_contract_enabled": case_fanout_contract_enabled(truth, mission_id),
        "real_mission_pass": False,
        "completion_authority": "INDEPENDENT_EVALUATION_AND_MISSION_SUFFICIENCY",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start or resume one durable RC7 BANK Mission")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--graph-version", choices=MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS, default=None)
    parser.add_argument("--input", action="append", default=[], metavar="NODE=REF")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = start_or_resume(r1_path=args.r1, mission_id=args.mission_id, release_id=args.release_id,
                                 goal=args.goal, external_inputs=_parse_inputs(args.input), graph_version=args.graph_version)
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
