"""Productized RC7 BANK Mission bootstrap and resume entrypoint.

This module is a thin durable activation layer over the RC7 R1-backed control
plane.  Graph identity is persisted in R1 so an existing Mission never changes
shape merely because a newer runtime is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .mission_graph import MissionTaskGraphCompiler
from .models import Evidence, Mission
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
        node = node.strip().upper()
        ref = ref.strip()
        if not node or not ref:
            raise BankMissionError("MISSION_INPUT_MUST_BE_NODE_EQUALS_REF")
        grouped.setdefault(node, []).append(ref)
    return {node: tuple(dict.fromkeys(refs)) for node, refs in grouped.items()}


def _mission_row(truth: TruthRuntime, mission_id: str) -> Optional[Mapping[str, object]]:
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


def _graph_evidence_id(mission_id: str, graph_version: str) -> str:
    raw = (mission_id + "\x1f" + graph_version).encode("utf-8")
    return "EVD-GRAPH-" + hashlib.sha256(raw).hexdigest()[:20]


def _persist_graph_contract(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    compiler: MissionTaskGraphCompiler,
    task_ids: Sequence[str],
) -> None:
    contract = compiler.contract()
    append_entity(
        truth,
        Evidence(
            evidence_id=_graph_evidence_id(mission_id, compiler.graph_version),
            mission_id=mission_id,
            kind=GRAPH_EVIDENCE_KIND,
            source_ref="runtime://mission-graph-compiler/%s" % compiler.graph_version,
            content_ref="mission-graph://%s/%s" % (
                compiler.graph_version,
                contract["contract_sha256"],
            ),
            subject_refs=list(task_ids),
            content_hash=str(contract["contract_sha256"]),
        ),
        release_id=release_id,
        artifact_version=1,
    )


def _persisted_graph_version(truth: TruthRuntime, mission_id: str) -> Optional[str]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == GRAPH_EVIDENCE_KIND
    ]
    if len(rows) > 1:
        raise BankMissionError("MISSION_GRAPH_CONTRACT_NOT_UNIQUE")
    if rows:
        source = str(rows[0].get("source_ref") or "")
        version = source.rsplit("/", 1)[-1].strip().lower()
        if version not in MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS:
            raise BankMissionError("MISSION_GRAPH_VERSION_UNSUPPORTED:%s" % version)
        return version

    # Compatibility for Missions created by the original RC7 package before
    # graph-version evidence existed.  Their persisted task inventory is the
    # authority; never silently upgrade them to v2 during resume.
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    if task_rows:
        nodes = {str(row.get("node") or "") for row in task_rows}
        if nodes.issubset(set(MissionTaskGraphCompiler.NODE_ORDER)):
            return MissionTaskGraphCompiler.GRAPH_V1
        if {"REALITY_RECON", "PRECONDITION_DATA", "REPORT"}.intersection(nodes):
            return MissionTaskGraphCompiler.GRAPH_V2
        raise BankMissionError("MISSION_GRAPH_VERSION_CANNOT_BE_INFERRED")
    return None


def _assert_resume_graph(
    truth: TruthRuntime,
    mission_id: str,
    external_inputs: Mapping[str, Sequence[str]],
    compiler: MissionTaskGraphCompiler,
) -> None:
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


def start_or_resume(
    *,
    r1_path: str,
    mission_id: str,
    release_id: str,
    goal: str,
    external_inputs: Optional[Mapping[str, Sequence[str]]] = None,
    graph_version: Optional[str] = None,
) -> Dict[str, object]:
    r1 = Path(_required(r1_path, "r1_path")).expanduser().resolve()
    mission_id = _required(mission_id, "mission_id")
    release_id = _required(release_id, "release_id")
    goal = _required(goal, "goal")
    r1.parent.mkdir(parents=True, exist_ok=True)

    normalized_inputs = dict(external_inputs or {})
    truth = TruthRuntime(r1)
    row = _mission_row(truth, mission_id)
    persisted_version = _persisted_graph_version(truth, mission_id)

    if row is None:
        selected_version = str(graph_version or MissionTaskGraphCompiler.DEFAULT_GRAPH_VERSION).lower()
        compiler = MissionTaskGraphCompiler(selected_version)
        control = ClosedLoopControlPlane.bootstrap(
            truth,
            Mission(mission_id=mission_id, release_id=release_id, goal=goal),
        )
        graph = compiler.install(control, mission_id, external_inputs=normalized_inputs)
        _persist_graph_contract(
            truth,
            mission_id=mission_id,
            release_id=release_id,
            compiler=compiler,
            task_ids=[task.task_id for task in graph.tasks],
        )
        action = "STARTED"
    else:
        _assert_resume_identity(row, release_id, goal)
        selected_version = persisted_version or MissionTaskGraphCompiler.GRAPH_V1
        if graph_version is not None and str(graph_version).lower() != selected_version:
            raise BankMissionError("MISSION_GRAPH_VERSION_MISMATCH")
        compiler = MissionTaskGraphCompiler(selected_version)
        _assert_resume_graph(truth, mission_id, normalized_inputs, compiler)
        control = ClosedLoopControlPlane(truth, release_id, mission_id)
        control.refresh_ready()
        action = "RESUMED"

    current = _mission_row(truth, mission_id)
    if current is None:
        raise BankMissionError("MISSION_TRUTH_MISSING_AFTER_START")
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    gap_rows = truth.query("rc7_gap", mission_id=mission_id)
    ready = sorted(
        (
            {"task_id": str(row["task_id"]), "node": str(row["node"])}
            for row in task_rows
            if row.get("state") == "READY"
        ),
        key=lambda item: (item["node"], item["task_id"]),
    )
    return {
        "status": action,
        "mission_id": mission_id,
        "release_id": release_id,
        "goal": goal,
        "graph_version": compiler.graph_version,
        "logical_stages": list(compiler.logical_stages),
        "conditional_stages": list(compiler.conditional_stages),
        "mission_state": str(current.get("state") or "UNKNOWN"),
        "sufficiency_state": str(current.get("sufficiency_state") or "UNKNOWN"),
        "r1_path": str(r1),
        "task_count": len(task_rows),
        "open_gap_count": len(
            [
                row
                for row in gap_rows
                if row.get("state")
                in {"OPEN", "PLANNED", "REPAIRING", "EVIDENCE_PENDING", "HUMAN_REQUIRED", "BLOCKED"}
            ]
        ),
        "ready_tasks": ready,
        "real_mission_pass": False,
        "completion_authority": "INDEPENDENT_EVALUATION_AND_MISSION_SUFFICIENCY",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start or resume one durable RC7 BANK Mission")
    parser.add_argument("--r1", required=True, help="Canonical R1 Event Stream JSONL path")
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument(
        "--graph-version",
        choices=MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS,
        default=None,
        help="Graph version for a new Mission; an existing Mission always resumes its persisted version",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NODE=REF",
        help="Bind an external durable source reference into a canonical Mission node",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = start_or_resume(
            r1_path=args.r1,
            mission_id=args.mission_id,
            release_id=args.release_id,
            goal=args.goal,
            external_inputs=_parse_inputs(args.input),
            graph_version=args.graph_version,
        )
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
