"""Fail-closed convergence authority for contracted RC7 Bank Missions.

Bank Final already replays these facts after a run. This authority moves the
same trust boundary into the product path: a graph-v2 Mission carrying the
Execution Recovery Contract cannot transition to CONVERGED until canonical
Mission/Node Tool, recovery, Actual Result/Oracle, Defect Review and Residual
Risk governance truth all pass from R1.

Legacy Missions without the additive recovery contract remain resumable and are
reported as NOT_ENFORCED; they are not silently upgraded to a new contract.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

from rc6_runtime.truth import TruthRuntime

from .defect_review_conformance import DefectReviewConformanceChecker
from .execution_recovery_conformance import (
    ExecutionRecoveryConformanceChecker,
    contract_row as execution_recovery_contract_row,
)
from .mission_conformance import MissionConformanceChecker
from .oracle_conformance import ActualResultOracleConformanceChecker


class MissionConvergenceConformanceError(RuntimeError):
    pass


RISK_GOVERNANCE_RECEIPT_TYPE = "RESIDUAL_RISK_CONVERGENCE_RECEIPT"


def canonical_execution_task_id(truth: TruthRuntime, mission_id: str) -> str:
    row = execution_recovery_contract_row(truth, mission_id)
    if row is None:
        return ""
    refs = [str(value) for value in list(row.get("subject_refs") or []) if str(value)]
    if len(refs) != 1:
        raise MissionConvergenceConformanceError(
            "CANONICAL_EXECUTION_CONTRACT_SUBJECT_INVALID:%d" % len(refs)
        )
    task_id = refs[0]
    rows = truth.query("rc7_task", task_id=task_id)
    if (
        len(rows) != 1
        or rows[0].get("mission_id") != mission_id
        or rows[0].get("node") != "EXECUTION"
    ):
        raise MissionConvergenceConformanceError(
            "CANONICAL_EXECUTION_TASK_INVALID:%s" % task_id
        )
    return task_id


@dataclass(frozen=True)
class MissionConvergenceConformanceResult:
    mission_id: str
    status: str
    enforced: bool
    canonical_execution_task_id: str
    mission_conformance: Dict[str, Any]
    execution_recovery_conformance: Dict[str, Any]
    actual_result_oracle_conformance: Dict[str, Any]
    defect_review_conformance: Dict[str, Any]
    residual_risk_conformance: Dict[str, Any]
    violations: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "enforced": self.enforced,
            "canonical_execution_task_id": self.canonical_execution_task_id,
            "mission_conformance": self.mission_conformance,
            "execution_recovery_conformance": self.execution_recovery_conformance,
            "actual_result_oracle_conformance": self.actual_result_oracle_conformance,
            "defect_review_conformance": self.defect_review_conformance,
            "residual_risk_conformance": self.residual_risk_conformance,
            "violations": list(self.violations),
        }


class MissionConvergenceConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check(self, mission_id: str) -> MissionConvergenceConformanceResult:
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise MissionConvergenceConformanceError("MISSION_ID_REQUIRED")
        contract = execution_recovery_contract_row(self.truth, mission_id)
        if contract is None:
            return MissionConvergenceConformanceResult(
                mission_id=mission_id,
                status="PASS",
                enforced=False,
                canonical_execution_task_id="",
                mission_conformance={"status": "NOT_ENFORCED"},
                execution_recovery_conformance={"status": "NOT_ENFORCED"},
                actual_result_oracle_conformance={"status": "NOT_ENFORCED"},
                defect_review_conformance={"status": "NOT_ENFORCED"},
                residual_risk_conformance={"status": "NOT_ENFORCED"},
                violations=(),
            )

        violations: List[str] = []
        task_id = canonical_execution_task_id(self.truth, mission_id)

        try:
            mission = MissionConformanceChecker(self.truth).check(mission_id)
            mission_payload = mission.as_dict()
            if mission.status != "PASS":
                violations.append(
                    "MISSION_CONFORMANCE_FAILED:%s" % ",".join(mission.violations)
                )
        except Exception as exc:
            mission_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("MISSION_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            recovery = ExecutionRecoveryConformanceChecker(self.truth).check_task(
                mission_id, task_id
            )
            recovery_payload = recovery.as_dict()
            if recovery.status != "PASS":
                violations.append(
                    "EXECUTION_RECOVERY_CONFORMANCE_FAILED:%s"
                    % ",".join(recovery.violations)
                )
        except Exception as exc:
            recovery_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("EXECUTION_RECOVERY_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            oracle = ActualResultOracleConformanceChecker(self.truth).check_task(
                mission_id, task_id
            )
            oracle_payload = oracle.as_dict()
            if oracle.status != "PASS":
                violations.append(
                    "ACTUAL_RESULT_ORACLE_CONFORMANCE_FAILED:%s"
                    % ",".join(oracle.violations)
                )
        except Exception as exc:
            oracle_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("ACTUAL_RESULT_ORACLE_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            defect = DefectReviewConformanceChecker(self.truth).check_mission(mission_id)
            defect_payload = defect.as_dict()
            if defect.status != "PASS":
                violations.append(
                    "DEFECT_REVIEW_CONFORMANCE_FAILED:%s"
                    % ",".join(defect.violations)
                )
        except Exception as exc:
            defect_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("DEFECT_REVIEW_CONFORMANCE_ERROR:%s" % str(exc))

        try:
            risk_payload, risk_violations = self._residual_risk_conformance(mission_id)
            violations.extend(risk_violations)
        except Exception as exc:
            risk_payload = {"status": "FAIL", "reason": str(exc)}
            violations.append("RESIDUAL_RISK_CONFORMANCE_ERROR:%s" % str(exc))

        deduped = tuple(dict.fromkeys(violations))
        return MissionConvergenceConformanceResult(
            mission_id=mission_id,
            status="PASS" if not deduped else "FAIL",
            enforced=True,
            canonical_execution_task_id=task_id,
            mission_conformance=mission_payload,
            execution_recovery_conformance=recovery_payload,
            actual_result_oracle_conformance=oracle_payload,
            defect_review_conformance=defect_payload,
            residual_risk_conformance=risk_payload,
            violations=deduped,
        )

    def require_pass(self, mission_id: str) -> MissionConvergenceConformanceResult:
        result = self.check(mission_id)
        if result.status != "PASS":
            raise MissionConvergenceConformanceError(
                "MISSION_CONVERGENCE_CONFORMANCE_FAILED:%s"
                % ",".join(result.violations)
            )
        return result

    def _residual_risk_conformance(self, mission_id: str):
        # Import lazily to preserve the existing control-plane import graph:
        # closed_loop_control -> mission_convergence_conformance. The registry
        # itself accepts a control-plane shaped object and therefore imports the
        # control plane for its runtime API. Loading it here occurs only after
        # rc7_runtime has fully initialized and avoids a circular module import.
        from .autonomous_residual_risk import ResidualRiskRegistry

        proxy = SimpleNamespace(truth=self.truth, mission_id=mission_id)
        summary = ResidualRiskRegistry(evidence_root=".").summary(proxy)
        if int(summary.get("risk_count") or 0) == 0:
            return {"status": "PASS", "triggered": False, "risk_count": 0}, []

        violations: List[str] = []
        pending = [str(x) for x in summary.get("pending_risk_ids") or []]
        if pending:
            violations.append("RESIDUAL_RISK_PENDING:%s" % ",".join(sorted(pending)))

        receipts = [
            row
            for row in self.truth.query("rc7_artifact", mission_id=mission_id)
            if row.get("artifact_type_name") == RISK_GOVERNANCE_RECEIPT_TYPE
            and row.get("state") == "VALID"
        ]
        if not receipts:
            violations.append("RESIDUAL_RISK_GOVERNANCE_CURRENT_RECEIPT_NOT_UNIQUE:0")
            return {
                "status": "FAIL",
                "triggered": True,
                "risk_count": summary.get("risk_count"),
                "pending_risk_ids": pending,
                "receipt_history_count": 0,
            }, violations

        current = {item["risk_id"]: item for item in summary.get("risks") or []}
        current_matches = []
        valid_history = []
        for receipt in receipts:
            artifact_id = str(receipt.get("artifact_id") or "")
            content_ref = str(receipt.get("content_ref") or "")
            if not content_ref.startswith("file://"):
                violations.append(
                    "RESIDUAL_RISK_GOVERNANCE_RECEIPT_FILE_REQUIRED:%s" % artifact_id
                )
                continue
            path = Path(content_ref[len("file://"):])
            if not path.is_file():
                violations.append(
                    "RESIDUAL_RISK_GOVERNANCE_RECEIPT_FILE_MISSING:%s" % artifact_id
                )
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if receipt.get("content_hash") != "sha256:" + digest:
                violations.append(
                    "RESIDUAL_RISK_GOVERNANCE_RECEIPT_HASH_MISMATCH:%s" % artifact_id
                )
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                violations.append(
                    "RESIDUAL_RISK_GOVERNANCE_RECEIPT_JSON_INVALID:%s" % artifact_id
                )
                continue
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version")
                != "RC7_1_RESIDUAL_RISK_CONVERGENCE_V1"
            ):
                violations.append(
                    "RESIDUAL_RISK_GOVERNANCE_RECEIPT_SCHEMA_INVALID:%s" % artifact_id
                )
                continue

            valid_history.append((receipt, payload, digest))
            recorded = {
                item["risk_id"]: item
                for item in payload.get("risks") or []
                if isinstance(item, dict) and item.get("risk_id")
            }
            if set(current) != set(recorded):
                continue
            matched = True
            for risk_id in sorted(current):
                expected = current[risk_id]
                actual = recorded[risk_id]
                for field in (
                    "revision",
                    "disposition",
                    "acceptance_ref",
                    "record_sha256",
                    "artifact_id",
                    "evidence_id",
                ):
                    if actual.get(field) != expected.get(field):
                        matched = False
                        break
                if not matched:
                    break
            if payload.get("all_dispositioned") is not True:
                matched = False
            if matched:
                current_matches.append((receipt, payload, digest))

        if len(current_matches) != 1:
            violations.append(
                "RESIDUAL_RISK_GOVERNANCE_CURRENT_RECEIPT_NOT_UNIQUE:%d"
                % len(current_matches)
            )
            return {
                "status": "FAIL",
                "triggered": True,
                "risk_count": summary.get("risk_count"),
                "pending_risk_ids": pending,
                "receipt_history_count": len(receipts),
                "valid_receipt_history_count": len(valid_history),
                "current_match_count": len(current_matches),
            }, violations

        receipt, _, digest = current_matches[0]
        return {
            "status": "PASS" if not violations else "FAIL",
            "triggered": True,
            "risk_count": summary.get("risk_count"),
            "pending_risk_ids": pending,
            "receipt_history_count": len(receipts),
            "valid_receipt_history_count": len(valid_history),
            "current_match_count": 1,
            "receipt_artifact_id": receipt.get("artifact_id"),
            "receipt_sha256": digest,
        }, violations
