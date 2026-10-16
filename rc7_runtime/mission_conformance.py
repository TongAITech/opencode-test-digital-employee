"""Fail-closed Mission Graph conformance checker.

This checker validates durable R1 truth against the versioned Mission graph
contract. It does not execute domain work and does not declare TEST_SUFFICIENT.
It is intended for field hardening, resume validation and clean qualification
before a Mission is allowed to progress under a newer runtime.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .mission_graph import MissionTaskGraphCompiler
from .node_tool_conformance import (
    NODE_TOOL_REQUIREMENTS,
    NodeToolConformanceChecker,
    NodeToolConformanceError,
    contract_row as node_tool_contract_row,
)


class MissionConformanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionConformanceResult:
    mission_id: str
    graph_version: str
    mission_state: str
    status: str
    violations: Tuple[str, ...]
    canonical_task_ids: Tuple[str, ...]
    ready_task_ids: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "graph_version": self.graph_version,
            "mission_state": self.mission_state,
            "status": self.status,
            "violations": list(self.violations),
            "canonical_task_ids": list(self.canonical_task_ids),
            "ready_task_ids": list(self.ready_task_ids),
        }


class MissionConformanceChecker:
    GRAPH_EVIDENCE_KIND = "MISSION_GRAPH_CONTRACT"
    FORBIDDEN_V2_TOP_LEVEL_NODES = {"PRECONDITION_DATA", "REPORT"}
    REPORT_ARTIFACT_TYPES = {"FINAL_REPORT", "MISSION_REPORT", "MISSION_REPORT_CANDIDATE"}
    ACTIVE_TASK_STATES = {
        "REGISTERED", "READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED",
        "EVALUATING", "REPAIR_REQUIRED", "BLOCKED", "HUMAN_REQUIRED",
        "FAILED", "STALE",
    }

    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check(self, mission_id: str) -> MissionConformanceResult:
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise MissionConformanceError("MISSION_ID_REQUIRED")
        missions = self.truth.query("rc7_mission", mission_id=mission_id)
        if len(missions) != 1:
            raise MissionConformanceError("MISSION_CONFORMANCE_REQUIRES_EXACTLY_ONE_MISSION")
        mission = missions[0]
        task_rows = self.truth.query("rc7_task", mission_id=mission_id)
        graph_version, graph_evidence = self._graph_version(mission_id, task_rows)
        compiler = MissionTaskGraphCompiler(graph_version)
        expected = compiler.compile(mission_id)
        actual = {str(row.get("task_id") or ""): row for row in task_rows}
        violations: List[str] = []

        try:
            node_tool_contract = node_tool_contract_row(self.truth, mission_id)
        except NodeToolConformanceError as exc:
            node_tool_contract = None
            violations.append("NODE_TOOL_CONTRACT_INVALID:%s" % str(exc))
        node_tool_checker = NodeToolConformanceChecker(self.truth)

        expected_ids = {task.task_id for task in expected.tasks}
        for task in expected.tasks:
            row = actual.get(task.task_id)
            if row is None:
                violations.append("CANONICAL_TASK_MISSING:%s" % task.node)
                continue
            if str(row.get("node") or "") != task.node:
                violations.append("CANONICAL_TASK_NODE_MISMATCH:%s" % task.node)
            if list(row.get("dependency_task_ids", [])) != list(task.dependency_task_ids):
                violations.append("CANONICAL_TASK_DEPENDENCY_MISMATCH:%s" % task.node)
            expected_type = "RUNTIME" if compiler.task_owner(task.node) == compiler.OWNER_RUNTIME else "PRODUCE"
            if str(row.get("task_type") or "") != expected_type:
                violations.append("CANONICAL_TASK_OWNER_TYPE_MISMATCH:%s" % task.node)
            self._check_self_evaluation(row, violations)
            if (
                node_tool_contract is not None
                and task.node in NODE_TOOL_REQUIREMENTS
                and str(row.get("state") or "") == "PASS"
            ):
                tool_result = node_tool_checker.check_task(mission_id, task.task_id)
                if tool_result.status != "PASS":
                    violations.append(
                        "NODE_TOOL_CONFORMANCE_FAILED:%s:%s" % (
                            task.node,
                            ",".join(tool_result.missing_capabilities),
                        )
                    )

        if graph_version == MissionTaskGraphCompiler.GRAPH_V2:
            if graph_evidence is None:
                violations.append("V2_GRAPH_CONTRACT_EVIDENCE_REQUIRED")
            else:
                expected_hash = str(compiler.contract()["contract_sha256"])
                if str(graph_evidence.get("content_hash") or "") != expected_hash:
                    violations.append("V2_GRAPH_CONTRACT_HASH_MISMATCH")
                source_ref = str(graph_evidence.get("source_ref") or "")
                if not source_ref.endswith("/v2"):
                    violations.append("V2_GRAPH_CONTRACT_VERSION_REF_MISMATCH")
            forbidden = sorted(
                str(row.get("node") or "")
                for row in task_rows
                if str(row.get("node") or "") in self.FORBIDDEN_V2_TOP_LEVEL_NODES
            )
            if forbidden:
                violations.append("V2_FORBIDDEN_TOP_LEVEL_TASK:%s" % ",".join(forbidden))
            reality = expected.task("REALITY_RECON")
            row = actual.get(reality.task_id)
            if row is not None and str(row.get("task_type") or "") != "RUNTIME":
                violations.append("REALITY_RECON_MUST_BE_RUNTIME_OWNED")
            if node_tool_contract is not None:
                covered = set(node_tool_contract.get("subject_refs") or [])
                missing_contract_tasks = sorted(
                    task.task_id for task in expected.tasks
                    if task.node in NODE_TOOL_REQUIREMENTS and task.task_id not in covered
                )
                if missing_contract_tasks:
                    violations.append(
                        "NODE_TOOL_CONTRACT_TASK_COVERAGE_MISSING:%s" % ",".join(missing_contract_tasks)
                    )

        canonical_rows = [row for task_id, row in actual.items() if task_id in expected_ids]
        mission_state = str(mission.get("state") or "UNKNOWN")
        if mission_state == "CONVERGED":
            nonpass = sorted(
                str(row.get("task_id")) for row in canonical_rows
                if str(row.get("state") or "") != "PASS"
            )
            if nonpass:
                violations.append("CONVERGED_MISSION_HAS_NONPASS_CANONICAL_TASKS:%s" % ",".join(nonpass))
        else:
            report_artifacts = sorted(
                str(row.get("artifact_id") or "")
                for row in self.truth.query("rc7_artifact", mission_id=mission_id)
                if str(row.get("artifact_type_name") or row.get("artifact_type") or "") in self.REPORT_ARTIFACT_TYPES
            )
            if report_artifacts:
                violations.append("FINAL_REPORT_BEFORE_CONVERGENCE:%s" % ",".join(report_artifacts))

        # A graph checker never treats workflow completion as sufficiency.
        if mission_state != "CONVERGED" and str(mission.get("sufficiency_state") or "") in {
            "SUFFICIENT", "SUFFICIENT_WITH_RESIDUAL_RISK"
        }:
            violations.append("TEST_SUFFICIENT_WITHOUT_CONVERGED_MISSION")

        ready = tuple(sorted(
            str(row.get("task_id")) for row in task_rows if str(row.get("state") or "") == "READY"
        ))
        return MissionConformanceResult(
            mission_id=mission_id,
            graph_version=graph_version,
            mission_state=mission_state,
            status="PASS" if not violations else "FAIL",
            violations=tuple(sorted(dict.fromkeys(violations))),
            canonical_task_ids=tuple(sorted(expected_ids)),
            ready_task_ids=ready,
        )

    def _graph_version(self, mission_id: str, task_rows: Sequence[Mapping[str, object]]):
        rows = [
            row for row in self.truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == self.GRAPH_EVIDENCE_KIND
        ]
        if len(rows) > 1:
            raise MissionConformanceError("MISSION_GRAPH_CONTRACT_NOT_UNIQUE")
        if rows:
            source_ref = str(rows[0].get("source_ref") or "")
            version = source_ref.rsplit("/", 1)[-1].strip().lower()
            if version not in MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS:
                raise MissionConformanceError("MISSION_GRAPH_VERSION_UNSUPPORTED:%s" % version)
            return version, rows[0]
        nodes = {str(row.get("node") or "") for row in task_rows}
        if "REALITY_RECON" in nodes or {"PRECONDITION_DATA", "REPORT"}.intersection(nodes):
            return MissionTaskGraphCompiler.GRAPH_V2, None
        if nodes and nodes.issubset(set(MissionTaskGraphCompiler.NODE_ORDER)):
            return MissionTaskGraphCompiler.GRAPH_V1, None
        raise MissionConformanceError("MISSION_GRAPH_VERSION_CANNOT_BE_INFERRED")

    def _check_self_evaluation(self, task_row: Mapping[str, object], violations: List[str]) -> None:
        evaluation_id = str(task_row.get("evaluation_id") or "")
        lease_owner = str(task_row.get("lease_owner") or "")
        if not evaluation_id or not lease_owner:
            return
        rows = self.truth.query("rc7_evaluation", evaluation_id=evaluation_id)
        if len(rows) != 1:
            violations.append("TASK_EVALUATION_NOT_UNIQUE:%s" % str(task_row.get("task_id") or ""))
            return
        if str(rows[0].get("evaluator_ref") or "") == lease_owner:
            violations.append("PRODUCER_SELF_EVALUATION:%s" % str(task_row.get("task_id") or ""))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate durable RC7 Mission Graph conformance")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = MissionConformanceChecker(TruthRuntime(Path(args.r1).expanduser().resolve())).check(args.mission_id)
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
