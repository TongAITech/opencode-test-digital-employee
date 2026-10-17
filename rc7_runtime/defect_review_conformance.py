"""Fail-closed Bank Final conformance for PRODUCT_DEFECT lifecycle truth.

Runtime defect controls already enforce reproduction, qualification, RCA, fix
verification and impact regression while they execute.  This module is the
read-only final authority that replays canonical R1 and proves those controls
were actually traversed before a PRODUCT_DEFECT Gap was resolved.

No product failure means the gate is NOT_TRIGGERED and passes.  Once a trusted
PRODUCT failure exists, terminal labels alone are insufficient: every Product
Gap must have a linked independently evaluated Defect disposition.  CLOSED
Defects additionally require the exact fix revision, original-case post-fix
PASS and distinct impact-regression PASS evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import rc6_runtime.execution_overlay  # noqa: F401 - register execution closure truth
from rc6_runtime.truth import TruthRuntime


TERMINAL_STATES = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}
QUALIFICATION_EVALUATOR = "rc7-defect-qualification-gate"
CONFIRM_EVALUATOR = "rc7-runtime-defect-confirmation-gate"
CLOSE_EVALUATOR = "rc7-runtime-defect-closure-gate"
FIX_VERIFICATION_TASK = "DEFECT_FIX_VERIFICATION"
IMPACT_REGRESSION_TASK = "DEFECT_IMPACT_REGRESSION"


class DefectReviewConformanceError(RuntimeError):
    pass


def _one(rows: Sequence[Mapping[str, Any]], code: str, violations: List[str]) -> Optional[Mapping[str, Any]]:
    if len(rows) != 1:
        violations.append("%s:%d" % (code, len(rows)))
        return None
    return rows[0]


def _evaluation(truth: TruthRuntime, evaluation_id: object) -> Optional[Mapping[str, Any]]:
    if not isinstance(evaluation_id, str) or not evaluation_id:
        return None
    rows = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
    return rows[0] if len(rows) == 1 else None


def _execution_artifact(
    truth: TruthRuntime,
    *,
    mission_id: str,
    gap_id: str,
    artifact_id: str,
    expected_task_type: str,
    violations: List[str],
) -> Tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]], Optional[Dict[str, Any]]]:
    artifact = _one(
        truth.query("rc7_artifact", artifact_id=artifact_id),
        "DEFECT_EXECUTION_ARTIFACT_NOT_UNIQUE:%s" % artifact_id,
        violations,
    )
    if artifact is None:
        return None, None, None
    if artifact.get("mission_id") != mission_id or artifact.get("artifact_type_name") != "EXECUTION_CONCLUSION":
        violations.append("DEFECT_EXECUTION_ARTIFACT_IDENTITY_INVALID:%s" % artifact_id)
        return artifact, None, None

    producer = str(artifact.get("producer_task_id") or "")
    task = _one(
        truth.query("rc7_task", task_id=producer),
        "DEFECT_EXECUTION_TASK_NOT_UNIQUE:%s" % artifact_id,
        violations,
    )
    if task is None:
        return artifact, None, None
    if (
        task.get("mission_id") != mission_id
        or task.get("node") != "EXECUTION"
        or task.get("task_type") != expected_task_type
        or task.get("state") != "PASS"
        or gap_id not in list(task.get("gap_refs") or [])
        or artifact_id not in list(task.get("output_artifact_refs") or [])
    ):
        violations.append("DEFECT_EXECUTION_TASK_IDENTITY_INVALID:%s" % artifact_id)

    evaluation = _evaluation(truth, task.get("evaluation_id"))
    if evaluation is None:
        violations.append("DEFECT_EXECUTION_EVALUATION_MISSING:%s" % artifact_id)

    content_ref = str(artifact.get("content_ref") or "")
    if not content_ref.startswith("file://"):
        violations.append("DEFECT_EXECUTION_RECORD_REF_INVALID:%s" % artifact_id)
        return artifact, task, None
    path = Path(content_ref[len("file://"):])
    if not path.is_file():
        violations.append("DEFECT_EXECUTION_RECORD_MISSING:%s" % artifact_id)
        return artifact, task, None
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if str(artifact.get("content_hash") or "") != "sha256:" + digest:
        violations.append("DEFECT_EXECUTION_RECORD_HASH_MISMATCH:%s" % artifact_id)
        return artifact, task, None
    try:
        payload = json.loads(raw.decode("utf-8"))
        record = payload["record"]
    except Exception:
        violations.append("DEFECT_EXECUTION_RECORD_INVALID:%s" % artifact_id)
        return artifact, task, None
    if not isinstance(record, dict):
        violations.append("DEFECT_EXECUTION_RECORD_NOT_OBJECT:%s" % artifact_id)
        return artifact, task, None
    if (
        str(record.get("status") or "").upper() != "PASS"
        or record.get("integrity_passed") is not True
        or record.get("assertion_passed") is not True
    ):
        violations.append("DEFECT_EXECUTION_TRUSTED_PASS_REQUIRED:%s" % artifact_id)

    if evaluation is not None:
        dims = evaluation.get("dimensions")
        if (
            evaluation.get("mission_id") != mission_id
            or evaluation.get("node") != "EXECUTION"
            or evaluation.get("result") != "PASS"
            or artifact_id not in list(evaluation.get("artifact_refs") or [])
            or not isinstance(dims, dict)
            or dims.get("test_result") != "PASS"
            or dims.get("conclusive") is not True
            or dims.get("attempt_id") != record.get("attempt_id")
        ):
            violations.append("DEFECT_EXECUTION_EVALUATION_INVALID:%s" % artifact_id)

    formal = []
    for evidence_id in list(artifact.get("evidence_refs") or []):
        rows = truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            continue
        row = rows[0]
        if (
            row.get("mission_id") == mission_id
            and row.get("kind") == "RUNTIME_EXECUTION_RECORD"
            and row.get("source_ref") == "runtime://formal-execution"
            and producer in list(row.get("subject_refs") or [])
            and str(record.get("attempt_id") or "") in list(row.get("subject_refs") or [])
            and row.get("content_ref") == artifact.get("content_ref")
            and row.get("content_hash") == artifact.get("content_hash")
        ):
            formal.append(row)
    if len(formal) != 1:
        violations.append("FORMAL_DEFECT_EXECUTION_RECORD_REQUIRED:%s" % artifact_id)
    return artifact, task, record


@dataclass(frozen=True)
class DefectReviewConformanceResult:
    mission_id: str
    status: str
    triggered: bool
    product_gap_ids: Tuple[str, ...]
    defect_ids: Tuple[str, ...]
    closed_defect_ids: Tuple[str, ...]
    violations: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "triggered": self.triggered,
            "product_gap_ids": list(self.product_gap_ids),
            "defect_ids": list(self.defect_ids),
            "closed_defect_ids": list(self.closed_defect_ids),
            "violations": list(self.violations),
        }


class DefectReviewConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check_mission(self, mission_id: str) -> DefectReviewConformanceResult:
        if not mission_id:
            raise DefectReviewConformanceError("MISSION_ID_REQUIRED")
        violations: List[str] = []
        product_gaps = [
            row for row in self.truth.query("rc7_gap", mission_id=mission_id)
            if row.get("category") == "PRODUCT_DEFECT"
        ]
        trusted_product_failures = [
            row for row in self.truth.query("rc7_evaluation", mission_id=mission_id)
            if row.get("node") == "EXECUTION"
            and isinstance(row.get("dimensions"), dict)
            and row["dimensions"].get("failure_class") == "PRODUCT"
            and row["dimensions"].get("test_result") == "FAIL"
        ]
        triggered = bool(product_gaps or trusted_product_failures)
        if not triggered:
            return DefectReviewConformanceResult(mission_id, "PASS", False, (), (), (), ())
        if trusted_product_failures and not product_gaps:
            violations.append("TRUSTED_PRODUCT_FAIL_WITHOUT_PRODUCT_GAP")

        qualified_defects: List[str] = []
        closed: List[str] = []
        for gap in product_gaps:
            gap_id = str(gap.get("gap_id") or "")
            prefix = gap_id or "unknown-gap"
            if gap.get("state") != "RESOLVED":
                violations.append("PRODUCT_DEFECT_GAP_NOT_RESOLVED:%s" % prefix)
            gap_states = [
                str(row.get("state") or "")
                for row in self.truth.projection.history("rc7_gap", gap_id)
            ]
            for required in ("REPAIRING", "EVIDENCE_PENDING", "RESOLVED"):
                if required not in gap_states:
                    violations.append("PRODUCT_DEFECT_GAP_LIFECYCLE_MISSING:%s:%s" % (prefix, required))

            defects = [
                row for row in self.truth.query("rc7_defect", mission_id=mission_id)
                if row.get("source_gap_id") == gap_id
            ]
            defect = _one(defects, "PRODUCT_DEFECT_RECORD_NOT_UNIQUE:%s" % prefix, violations)
            if defect is None:
                continue
            defect_id = str(defect.get("defect_id") or "")
            qualified_defects.append(defect_id)
            state = str(defect.get("state") or "")
            if state not in TERMINAL_STATES:
                violations.append("DEFECT_TERMINAL_DISPOSITION_REQUIRED:%s:%s" % (defect_id, state))

            owners = [
                row for row in self.truth.query("rc7_task", mission_id=mission_id)
                if row.get("node") == "DEFECT"
                and row.get("task_type") == "QUALIFY_DEFECT"
                and gap_id in list(row.get("gap_refs") or [])
            ]
            owner = _one(owners, "DEFECT_OWNER_TASK_NOT_UNIQUE:%s" % defect_id, violations)
            resolution_id = str(gap.get("resolution_evaluation_id") or "")
            resolution = _evaluation(self.truth, resolution_id)
            if owner is not None:
                if owner.get("state") != "PASS" or owner.get("evaluation_id") != resolution_id:
                    violations.append("DEFECT_OWNER_TASK_NOT_RESOLVED_BY_GAP_EVALUATION:%s" % defect_id)
            if resolution is None:
                violations.append("DEFECT_RESOLUTION_EVALUATION_MISSING:%s" % defect_id)
            else:
                dims = resolution.get("dimensions")
                if (
                    resolution.get("mission_id") != mission_id
                    or resolution.get("node") != "DEFECT"
                    or resolution.get("result") != "PASS"
                    or not isinstance(dims, dict)
                    or dims.get("defect_id") != defect_id
                    or dims.get("defect_state") != state
                    or defect.get("latest_evaluation_id") != resolution_id
                ):
                    violations.append("DEFECT_RESOLUTION_EVALUATION_INVALID:%s" % defect_id)
                if owner is not None:
                    owner_ref = str(owner.get("lease_owner") or "")
                    if owner_ref and resolution.get("evaluator_ref") == owner_ref:
                        violations.append("DEFECT_SELF_REVIEW_FORBIDDEN:%s" % defect_id)
                    outputs = set(owner.get("output_artifact_refs") or [])
                    if outputs and not outputs.intersection(set(resolution.get("artifact_refs") or [])):
                        violations.append("DEFECT_RESOLUTION_OUTPUT_REF_MISSING:%s" % defect_id)

            history = self.truth.projection.history("rc7_defect", defect_id)
            evidence_ready = [row for row in history if row.get("state") == "EVIDENCE_READY"]
            if not evidence_ready:
                violations.append("DEFECT_QUALIFICATION_HISTORY_MISSING:%s" % defect_id)
            else:
                qualification_id = evidence_ready[-1].get("latest_evaluation_id")
                qualification = _evaluation(self.truth, qualification_id)
                dims = qualification.get("dimensions") if qualification else None
                predicates = dims.get("qualification") if isinstance(dims, dict) else None
                if (
                    qualification is None
                    or qualification.get("mission_id") != mission_id
                    or qualification.get("node") != "DEFECT"
                    or qualification.get("result") != "PASS"
                    or qualification.get("evaluator_ref") != QUALIFICATION_EVALUATOR
                    or not isinstance(predicates, dict)
                    or not predicates
                    or not all(value is True for value in predicates.values())
                ):
                    violations.append("DEFECT_QUALIFICATION_EVALUATION_INVALID:%s" % defect_id)

            if int(defect.get("reproduction_attempts") or 0) < 1 or int(defect.get("reproduction_passes") or 0) < 1:
                violations.append("DEFECT_REPRODUCTION_PROOF_REQUIRED:%s" % defect_id)
            reproduction_tasks = [
                row for row in self.truth.query("rc7_task", mission_id=mission_id)
                if row.get("node") == "EXECUTION"
                and row.get("task_type") == "DEFECT_REPRODUCTION"
                and gap_id in list(row.get("gap_refs") or [])
                and row.get("state") == "PASS"
            ]
            if not reproduction_tasks:
                violations.append("DEFECT_REPRODUCTION_TASK_PASS_REQUIRED:%s" % defect_id)
            else:
                reproduced = False
                for task in reproduction_tasks:
                    evaluation = _evaluation(self.truth, task.get("evaluation_id"))
                    dims = evaluation.get("dimensions") if evaluation else None
                    if (
                        evaluation is not None
                        and evaluation.get("node") == "EXECUTION"
                        and evaluation.get("result") == "PASS"
                        and isinstance(dims, dict)
                        and dims.get("purpose") == "DEFECT_REPRODUCTION"
                        and dims.get("conclusive") is True
                        and dims.get("reproduced") is True
                    ):
                        reproduced = True
                        break
                if not reproduced:
                    violations.append("DEFECT_CONCLUSIVE_REPRODUCTION_EVALUATION_REQUIRED:%s" % defect_id)

            if state == "DUPLICATE":
                duplicate_of = str(defect.get("duplicate_of") or "")
                targets = self.truth.query("rc7_defect", defect_id=duplicate_of) if duplicate_of else []
                if len(targets) != 1 or targets[0].get("mission_id") != mission_id or targets[0].get("state") == "NOT_A_DEFECT":
                    violations.append("DEFECT_DUPLICATE_TARGET_INVALID:%s" % defect_id)
            elif state == "CLOSED":
                closed.append(defect_id)
                self._check_closed(
                    mission_id=mission_id,
                    gap_id=gap_id,
                    defect=defect,
                    history=history,
                    resolution=resolution,
                    violations=violations,
                )

        deduped = tuple(dict.fromkeys(violations))
        return DefectReviewConformanceResult(
            mission_id=mission_id,
            status="PASS" if not deduped else "FAIL",
            triggered=True,
            product_gap_ids=tuple(sorted(str(row.get("gap_id") or "") for row in product_gaps)),
            defect_ids=tuple(sorted(set(qualified_defects))),
            closed_defect_ids=tuple(sorted(set(closed))),
            violations=deduped,
        )

    def _check_closed(
        self,
        *,
        mission_id: str,
        gap_id: str,
        defect: Mapping[str, Any],
        history: Sequence[Mapping[str, Any]],
        resolution: Optional[Mapping[str, Any]],
        violations: List[str],
    ) -> None:
        defect_id = str(defect.get("defect_id") or "")
        hypothesis = defect.get("root_cause_hypothesis")
        if not isinstance(hypothesis, dict) or not hypothesis.get("hypothesis_id") or not hypothesis.get("evidence_refs"):
            violations.append("DEFECT_RCA_HYPOTHESIS_REQUIRED:%s" % defect_id)
        else:
            for evidence_id in list(hypothesis.get("evidence_refs") or []):
                rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
                if len(rows) != 1 or rows[0].get("mission_id") != mission_id or defect_id not in list(rows[0].get("subject_refs") or []):
                    violations.append("DEFECT_RCA_EVIDENCE_INVALID:%s:%s" % (defect_id, evidence_id))

        confirm = [
            row for row in self.truth.query("rc7_evaluation", mission_id=mission_id)
            if row.get("evaluator_ref") == CONFIRM_EVALUATOR
            and isinstance(row.get("dimensions"), dict)
            and row["dimensions"].get("defect_id") == defect_id
            and row["dimensions"].get("defect_state") == "CONFIRMED"
        ]
        if len(confirm) != 1:
            violations.append("DEFECT_CONFIRMATION_EVALUATION_REQUIRED:%s" % defect_id)
        elif not any(
            row.get("state") in {"FIX_PENDING", "FIX_DETECTED", "REGRESSION_TESTING", "CLOSED"}
            and row.get("latest_evaluation_id") == confirm[0].get("evaluation_id")
            for row in history
        ):
            violations.append("DEFECT_CONFIRMATION_LINEAGE_MISSING:%s" % defect_id)

        fix_revision = str(defect.get("fix_revision") or "")
        if not fix_revision:
            violations.append("DEFECT_FIX_REVISION_REQUIRED:%s" % defect_id)
        fix_evidence = [
            row for row in self.truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == "FIX_REVISION_EVIDENCE"
            and defect_id in list(row.get("subject_refs") or [])
            and fix_revision in list(row.get("subject_refs") or [])
        ] if fix_revision else []
        if len(fix_evidence) < 1:
            violations.append("DEFECT_FIX_REVISION_EVIDENCE_REQUIRED:%s" % defect_id)

        verification_refs = tuple(dict.fromkeys(str(value) for value in list(defect.get("verification_refs") or []) if str(value)))
        regression_refs = tuple(dict.fromkeys(str(value) for value in list(defect.get("regression_refs") or []) if str(value)))
        if len(verification_refs) != 1:
            violations.append("DEFECT_FIX_VERIFICATION_ARTIFACT_REQUIRED:%s" % defect_id)
        if not regression_refs:
            violations.append("DEFECT_IMPACT_REGRESSION_ARTIFACT_REQUIRED:%s" % defect_id)

        verification_task = None
        verification_record = None
        if len(verification_refs) == 1:
            _, verification_task, verification_record = _execution_artifact(
                self.truth,
                mission_id=mission_id,
                gap_id=gap_id,
                artifact_id=verification_refs[0],
                expected_task_type=FIX_VERIFICATION_TASK,
                violations=violations,
            )
            if verification_record is not None:
                if str(verification_record.get("tc_id") or "") not in set(defect.get("test_case_ids") or []):
                    violations.append("DEFECT_FIX_VERIFICATION_ORIGINAL_CASE_REQUIRED:%s" % defect_id)
                if str(verification_record.get("attempt_id") or "") in set(defect.get("execution_attempt_ids") or []):
                    violations.append("DEFECT_FIX_VERIFICATION_NEW_ATTEMPT_REQUIRED:%s" % defect_id)

        regression_cases: List[str] = []
        for artifact_id in regression_refs:
            _, task, record = _execution_artifact(
                self.truth,
                mission_id=mission_id,
                gap_id=gap_id,
                artifact_id=artifact_id,
                expected_task_type=IMPACT_REGRESSION_TASK,
                violations=violations,
            )
            if task is not None and verification_task is not None:
                if str(verification_task.get("task_id") or "") not in list(task.get("dependency_task_ids") or []):
                    violations.append("DEFECT_REGRESSION_DEPENDENCY_INVALID:%s:%s" % (defect_id, artifact_id))
            if record is not None:
                regression_cases.append(str(record.get("tc_id") or ""))
        if regression_cases and not any(case_id not in set(defect.get("test_case_ids") or []) for case_id in regression_cases):
            violations.append("DEFECT_DISTINCT_IMPACT_REGRESSION_CASE_REQUIRED:%s" % defect_id)

        if resolution is not None:
            dims = resolution.get("dimensions")
            if (
                resolution.get("evaluator_ref") != CLOSE_EVALUATOR
                or not isinstance(dims, dict)
                or dims.get("fix_revision") != fix_revision
                or dims.get("fix_verified") is not True
                or dims.get("impact_regression_passed") is not True
                or verification_record is None
                or dims.get("verification_attempt_id") != verification_record.get("attempt_id")
                or set(dims.get("regression_case_ids") or []) != set(regression_cases)
            ):
                violations.append("DEFECT_CLOSURE_EVALUATION_INVALID:%s" % defect_id)
