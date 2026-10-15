"""Productized RC7 BANK Mission bootstrap and resume entrypoint.

This module is deliberately a thin durable activation layer over the RC7
R1-backed control plane.  It does not perform professional test work and it
never converts startup success into Mission PASS.  Its responsibilities are:

* bind one explicit R1 Event Stream path;
* bootstrap a new Mission plus the canonical task graph exactly once;
* resume the same durable Mission after process/session restart;
* fail closed if callers try to reuse a Mission id for a different release or
  goal; and
* expose machine-readable startup/status facts for launch scripts, the admin
  platform and final qualification to share.

Professional work remains Worker-owned and acceptance remains independent
Evaluator/Mission-sufficiency authority.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .mission_graph import MissionTaskGraphCompiler
from .models import Mission


class BankMissionError(RuntimeError):
    pass


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


def _assert_resume_graph(
    truth: TruthRuntime,
    mission_id: str,
    external_inputs: Mapping[str, Sequence[str]],
) -> None:
    """Protect the durable graph while allowing context-free Session resume.

    Stable task/dependency identity is always checked.  External source refs are
    checked only when the caller explicitly supplies them again; otherwise the
    persisted R1 graph is authoritative and no chat/session context is needed.
    """
    expected = MissionTaskGraphCompiler().compile(mission_id, external_inputs=external_inputs)
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
) -> Dict[str, object]:
    r1 = Path(_required(r1_path, "r1_path")).expanduser().resolve()
    mission_id = _required(mission_id, "mission_id")
    release_id = _required(release_id, "release_id")
    goal = _required(goal, "goal")
    r1.parent.mkdir(parents=True, exist_ok=True)

    normalized_inputs = dict(external_inputs or {})
    truth = TruthRuntime(r1)
    row = _mission_row(truth, mission_id)
    if row is None:
        control = ClosedLoopControlPlane.bootstrap(
            truth,
            Mission(mission_id=mission_id, release_id=release_id, goal=goal),
        )
        MissionTaskGraphCompiler().install(
            control,
            mission_id,
            external_inputs=normalized_inputs,
        )
        action = "STARTED"
    else:
        _assert_resume_identity(row, release_id, goal)
        _assert_resume_graph(truth, mission_id, normalized_inputs)
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
        )
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())