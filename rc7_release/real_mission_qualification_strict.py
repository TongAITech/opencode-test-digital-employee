from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

import rc6_runtime.agent_runtime  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.defect_review_conformance import DefectReviewConformanceChecker
from rc7_runtime.execution_recovery_conformance import (
    ExecutionRecoveryConformanceChecker,
    contract_enabled as execution_recovery_contract_enabled,
    contract_row as execution_recovery_contract_row,
)
from rc7_runtime.mission_conformance import MissionConformanceChecker
from rc7_runtime.node_tool_conformance import contract_enabled as node_tool_contract_enabled
from rc7_runtime.oracle_conformance import ActualResultOracleConformanceChecker
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

from .real_mission_qualification import DOMAIN_NODES, evaluate_real_mission


SCHEMA_VERSION = "pfc.aitest.rc7.real-mission-qualification.strict.v4"
STRICT_DOMAIN_NODES = set(DOMAIN_NODES) | {"EXECUTION"}


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


def _task_scoped_dsh_runtime_workers(
    truth: TruthRuntime,
    *,
    mission_id: str,
) -> Dict[str, Set[str]]:
    task_workers: Dict[str, Set[str]] = {}
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != "DSH_RUNTIME_PROOF":
            continue
        source_ref = row.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref.startswith("dsh://worker/"):
            continue
        worker = source_ref[len("dsh://worker/"):]
        if not worker:
            continue
        for subject in row.get("subject_refs", []):
            if isinstance(subject, str) and subject:
                task_workers.setdefault(subject, set()).add(worker)
    return task_workers


def _canonical_execution_task_id(
    truth: TruthRuntime,
    *,
    mission_id: str,
    blockers: List[str],
) -> str:
    """Resolve the frozen graph-v2 EXECUTION task from its recovery contract.

    Defect handling legitimately creates additional EXECUTION tasks for
    reproduction/fix verification/regression. They must never make Bank Final
    misidentify the canonical top-level graph node.
    """
    try:
        row = execution_recovery_contract_row(truth, mission_id)
    except Exception as exc:
        blockers.append("BANK_FIELD_EXECUTION_RECOVERY_CONTRACT_INVALID:%s" % str(exc))
        return ""
    if row is None:
        return ""
    refs = [str(value) for value in list(row.get("subject_refs") or []) if str(value)]
    if len(refs) != 1:
        blockers.append("BANK_FIELD_CANONICAL_EXECUTION_CONTRACT_SUBJECT_INVALID:%d" % len(refs))
        return ""
    task_id = refs[0]
    rows = truth.query("rc7_task", task_id=task_id)
    if (
        len(rows) != 1
        or rows[0].get("mission_id") != mission_id
        or rows[0].get("node") != "EXECUTION"
    ):
        blockers.append("BANK_FIELD_CANONICAL_EXECUTION_TASK_INVALID:%s" % task_id)
        return ""
    return task_id


def _bank_field_contracts(
    truth: TruthRuntime,
    *,
    mission_id: str,
) -> Dict[str, Any]:
    """Read-only Bank Final conformance from canonical R1 truth.

    Generic/legacy qualification intentionally does not require these graph-v2
    field gates. Bank Final opts in so old Missions stay resumable but cannot
    certify a new RC7 package. Recovery proves attempt ordering; Oracle proves
    actual-result/assertion integrity; Defect Review proves any PRODUCT_DEFECT
    disposition traversed reproduction/review/fix/regression rather than being
    closed by label alone.
    """
    blockers: List[str] = []
    try:
        mission = MissionConformanceChecker(truth).check(mission_id)
        mission_payload = mission.as_dict()
        if mission.status != "PASS":
            blockers.append(
                "BANK_FIELD_MISSION_CONFORMANCE_FAILED:%s"
                % ",".join(mission.violations)
            )
    except Exception as exc:
        mission_payload = {"status": "FAIL", "reason": str(exc)}
        blockers.append("BANK_FIELD_MISSION_CONFORMANCE_ERROR:%s" % str(exc))

    node_contract = node_tool_contract_enabled(truth, mission_id)
    if not node_contract:
        blockers.append("BANK_FIELD_NODE_TOOL_CONTRACT_REQUIRED")

    recovery_contract = execution_recovery_contract_enabled(truth, mission_id)
    if not recovery_contract:
        blockers.append("BANK_FIELD_EXECUTION_RECOVERY_CONTRACT_REQUIRED")

    recovery_payload: Dict[str, Any] = {
        "status": "NOT_ENFORCED" if not recovery_contract else "NOT_READY",
    }
    oracle_payload: Dict[str, Any] = {"status": "NOT_READY"}
    execution_task_id = _canonical_execution_task_id(
        truth,
        mission_id=mission_id,
        blockers=blockers,
    ) if recovery_contract else ""
    if recovery_contract and execution_task_id:
        try:
            recovery = ExecutionRecoveryConformanceChecker(truth).check_task(
                mission_id,
                execution_task_id,
            )
            recovery_payload = recovery.as_dict()
            if recovery.status != "PASS":
                blockers.append(
                    "BANK_FIELD_EXECUTION_RECOVERY_FAILED:%s"
                    % ",".join(recovery.violations)
                )
        except Exception as exc:
            recovery_payload = {"status": "FAIL", "reason": str(exc)}
            blockers.append("BANK_FIELD_EXECUTION_RECOVERY_ERROR:%s" % str(exc))

        try:
            oracle = ActualResultOracleConformanceChecker(truth).check_task(
                mission_id,
                execution_task_id,
            )
            oracle_payload = oracle.as_dict()
            if oracle.status != "PASS":
                blockers.append(
                    "BANK_FIELD_ACTUAL_RESULT_ORACLE_FAILED:%s"
                    % ",".join(oracle.violations)
                )
        except Exception as exc:
            oracle_payload = {"status": "FAIL", "reason": str(exc)}
            blockers.append("BANK_FIELD_ACTUAL_RESULT_ORACLE_ERROR:%s" % str(exc))
    elif recovery_contract:
        recovery_payload = {"status": "FAIL", "reason": "CANONICAL_EXECUTION_TASK_NOT_RESOLVED"}
        oracle_payload = dict(recovery_payload)

    try:
        defect_review = DefectReviewConformanceChecker(truth).check_mission(mission_id)
        defect_payload = defect_review.as_dict()
        if defect_review.status != "PASS":
            blockers.append(
                "BANK_FIELD_DEFECT_REVIEW_FAILED:%s"
                % ",".join(defect_review.violations)
            )
    except Exception as exc:
        defect_payload = {"status": "FAIL", "reason": str(exc)}
        blockers.append("BANK_FIELD_DEFECT_REVIEW_ERROR:%s" % str(exc))

    return {
        "status": "PASS" if not blockers else "HOLD",
        "mission_conformance": mission_payload,
        "node_tool_contract": "PASS" if node_contract else "HOLD",
        "execution_recovery_contract": "PASS" if recovery_contract else "HOLD",
        "canonical_execution_task_id": execution_task_id,
        "execution_recovery_conformance": recovery_payload,
        "actual_result_oracle_conformance": oracle_payload,
        "defect_review_conformance": defect_payload,
        "blocking_reasons": blockers,
    }


def evaluate_real_mission_strict(
    *,
    r1_path: str,
    mission_id: str,
    source_commit: str,
    require_bank_field_conformance: bool = False,
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
    dsh_runtime_workers = _task_scoped_dsh_runtime_workers(truth, mission_id=mission_id)
    task_proof: Dict[str, Dict[str, Any]] = {}

    domain_tasks = [
        row
        for row in truth.query("rc7_task", mission_id=mission_id)
        if row.get("node") in STRICT_DOMAIN_NODES
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
        task_dsh_workers = sorted(dsh_runtime_workers.get(task_id, set()))
        owner_dsh_runtime_proven = bool(owner and owner in task_dsh_workers)
        task_proof[task_id] = {
            "lease_owner": owner,
            "dsh_runtime_workers": task_dsh_workers,
            "owner_dsh_runtime_proven": owner_dsh_runtime_proven,
            "tool_receipts": owner_receipts,
            "task_scope": "task:%s" % task_id,
            "proven": bool(owner and owner_dsh_runtime_proven and owner_receipts),
        }
        if not owner_dsh_runtime_proven:
            blockers.append("DOMAIN_TASK_DSH_OWNER_PROOF_MISSING:%s" % task_id)
        if not owner_receipts:
            blockers.append("DOMAIN_TASK_REAL_TOOL_CALL_MISSING:%s" % task_id)

    bank_field = {
        "status": "NOT_REQUIRED",
        "blocking_reasons": [],
    }
    if require_bank_field_conformance:
        bank_field = _bank_field_contracts(truth, mission_id=mission_id)
        blockers.extend(bank_field.get("blocking_reasons", []))

    deduped: List[str] = []
    for blocker in blockers:
        if blocker not in deduped:
            deduped.append(blocker)

    result["schema_version"] = SCHEMA_VERSION
    result["qualification_kind"] = "BANK_REAL_MISSION_STRICT_TASK_RECEIPTS"
    result["task_scoped_worker_proof"] = task_proof
    result["bank_field_conformance_required"] = bool(require_bank_field_conformance)
    result["bank_field_conformance"] = bank_field
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
    parser.add_argument("--require-bank-field-conformance", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_real_mission_strict(
        r1_path=args.r1,
        mission_id=args.mission_id,
        source_commit=args.source_commit,
        require_bank_field_conformance=args.require_bank_field_conformance,
    )
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
