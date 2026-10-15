from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

import rc6_runtime.agent_runtime  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

from .real_mission_qualification import DOMAIN_NODES, evaluate_real_mission


SCHEMA_VERSION = "pfc.aitest.rc7.real-mission-qualification.strict.v1"


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _task_scoped_receipts(
    truth: TruthRuntime,
    *,
    mission_id: str,
) -> Dict[str, Set[str]]:
    receipts: Dict[str, Set[str]] = {}
    for event in truth.store.iter_raw():
        if event.get("event_type") != "WORKER_TOOL_CALLED":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("mission_id") != mission_id:
            continue
        worker = payload.get("worker_instance_id")
        scope = payload.get("scope")
        tool_call = payload.get("tool_call")
        if not isinstance(worker, str) or not worker:
            continue
        if not isinstance(scope, str) or not scope.startswith("task:"):
            continue
        if not isinstance(tool_call, dict):
            continue
        call_ref = tool_call.get("call_ref")
        if not isinstance(call_ref, str) or not call_ref.strip():
            continue
        task_id = scope[len("task:"):]
        if not task_id:
            continue
        receipts.setdefault(task_id, set()).add("%s|%s" % (worker, call_ref.strip()))
    return receipts


def evaluate_real_mission_strict(
    *,
    r1_path: str,
    mission_id: str,
    source_commit: str,
) -> Dict[str, Any]:
    result = evaluate_real_mission(
        r1_path=r1_path,
        mission_id=mission_id,
        source_commit=source_commit,
    )
    blockers = list(result.get("blocking_reasons", []))

    install_rc7_truth_overlay()
    truth = TruthRuntime(Path(r1_path).resolve())
    scoped = _task_scoped_receipts(truth, mission_id=mission_id)
    task_proof: Dict[str, Dict[str, Any]] = {}

    domain_tasks = [
        row
        for row in truth.query("rc7_task", mission_id=mission_id)
        if row.get("node") in DOMAIN_NODES
        and row.get("task_type") != "EVALUATE"
        and row.get("state") == "PASS"
    ]
    for task in domain_tasks:
        task_id = str(task.get("task_id", ""))
        owner = str(task.get("lease_owner") or "")
        task_receipts = sorted(scoped.get(task_id, set()))
        owner_receipts = [
            value.split("|", 1)[1]
            for value in task_receipts
            if owner and value.startswith(owner + "|")
        ]
        task_proof[task_id] = {
            "lease_owner": owner,
            "tool_receipts": owner_receipts,
            "task_scope": "task:%s" % task_id,
            "proven": bool(owner and owner_receipts),
        }
        if not owner_receipts:
            blockers.append("DOMAIN_TASK_REAL_TOOL_CALL_MISSING:%s" % task_id)

    # Preserve stable order while eliminating duplicate blockers inherited from
    # the base qualification or repeated malformed evidence.
    deduped: List[str] = []
    for blocker in blockers:
        if blocker not in deduped:
            deduped.append(blocker)

    result["schema_version"] = SCHEMA_VERSION
    result["qualification_kind"] = "BANK_REAL_MISSION_STRICT_TASK_RECEIPTS"
    result["task_scoped_worker_proof"] = task_proof
    result["blocking_reasons"] = deduped
    result["status"] = "PASS" if not deduped else "HOLD"
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.real_mission_qualification_strict")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_real_mission_strict(
        r1_path=args.r1,
        mission_id=args.mission_id,
        source_commit=args.source_commit,
    )
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
