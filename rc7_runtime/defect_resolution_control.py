"""Evidence-backed RC7 Defect resolution control.

Qualification only proves that a trusted PRODUCT failure deserves a Defect
candidate.  This controller owns the later lifecycle: evidence-backed RCA,
engineering confirmation, exact fix revision detection, original-case
verification, impact regression, and terminal PRODUCT_DEFECT Gap resolution.

No boolean such as ``fix_verified=True`` is accepted.  Fix/verification/
regression facts must already exist in the same Mission's R1 truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rc6_runtime.execution import ExecutionRecord

from .closed_loop_control import ClosedLoopControlPlane
from .defect_loop import DefectClosedLoop, DefectRecord, DefectStatus, RootCauseHypothesis
from .models import Evaluation, EvaluationResult, Evidence, TaskStatus
from .truth_overlay import append_entity


class DefectResolutionControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class DefectResolutionResult:
    defect_id: str
    defect_state: str
    fix_revision: str
    verification_artifact_id: str
    regression_artifact_ids: Tuple[str, ...]
    evaluation_id: str
    defect_task_state: str
    product_gap_state: str


class DefectResolutionControl:
    CONFIRM_EVALUATOR = "rc7-runtime-defect-confirmation-gate"
    CLOSE_EVALUATOR = "rc7-runtime-defect-closure-gate"

    def confirm_root_cause(
        self,
        control: ClosedLoopControlPlane,
        defect_id: str,
        *,
        hypothesis: RootCauseHypothesis,
    ) -> DefectRecord:
        defect = self._defect(control, defect_id)
        if defect.state != DefectStatus.EVIDENCE_READY:
            raise DefectResolutionControlError("DEFECT_EVIDENCE_READY_REQUIRED_FOR_CONFIRMATION")
        self._require_evidence_refs(
            control,
            hypothesis.evidence_refs,
            defect_id=defect.defect_id,
            required_kind=None,
        )
        loop = DefectClosedLoop()
        loop.attach_root_cause_hypothesis(defect, hypothesis)
        loop.transition(defect, DefectStatus.READY_FOR_REVIEW)

        task = self._owner_task(control, defect.source_gap_id)
        evaluation = Evaluation(
            evaluation_id=self._stable_id(
                "EVAL-DEFECT-CONFIRM",
                defect.defect_id,
                hypothesis.hypothesis_id,
                *hypothesis.evidence_refs,
            ),
            mission_id=control.mission_id,
            node="DEFECT",
            artifact_refs=list(task.output_artifact_refs),
            result=EvaluationResult.PASS,
            evaluator_ref=self.CONFIRM_EVALUATOR,
            dimensions={
                "defect_id": defect.defect_id,
                "defect_state": DefectStatus.CONFIRMED.value,
                "root_cause_hypothesis_id": hypothesis.hypothesis_id,
                "root_cause_confidence": hypothesis.confidence,
            },
            evidence_refs=list(hypothesis.evidence_refs),
        )
        append_entity(control.truth, evaluation, release_id=control.release_id, artifact_version=1)
        loop.transition(defect, DefectStatus.CONFIRMED, evaluation_id=evaluation.evaluation_id)
        loop.transition(defect, DefectStatus.FIX_PENDING)
        self._persist_next(control, defect)
        return defect

    def detect_fix(
        self,
        control: ClosedLoopControlPlane,
        defect_id: str,
        *,
        fix_revision: str,
        fix_evidence_id: str,
    ) -> DefectRecord:
        defect = self._defect(control, defect_id)
        if defect.state not in {DefectStatus.FIX_PENDING, DefectStatus.REOPENED}:
            raise DefectResolutionControlError("DEFECT_FIX_PENDING_REQUIRED")
        revision = str(fix_revision or "").strip()
        if not revision:
            raise DefectResolutionControlError("DEFECT_FIX_REVISION_REQUIRED")
        row = self._require_evidence_refs(
            control,
            (fix_evidence_id,),
            defect_id=defect.defect_id,
            required_kind="FIX_REVISION_EVIDENCE",
        )[0]
        subjects = set(row.get("subject_refs", []))
        if revision not in subjects:
            raise DefectResolutionControlError("FIX_REVISION_EVIDENCE_REVISION_MISMATCH")
        loop = DefectClosedLoop()
        if defect.state == DefectStatus.REOPENED:
            loop.transition(defect, DefectStatus.FIX_PENDING)
        if fix_evidence_id not in defect.evidence_refs:
            defect.evidence_refs.append(fix_evidence_id)
        loop.transition(defect, DefectStatus.FIX_DETECTED, fix_revision=revision)
        self._persist_next(control, defect)
        return defect

    def close_after_verification(
        self,
        control: ClosedLoopControlPlane,
        defect_id: str,
        *,
        verification_artifact_id: str,
        regression_artifact_ids: Sequence[str],
    ) -> DefectResolutionResult:
        defect = self._defect(control, defect_id)
        if defect.state != DefectStatus.FIX_DETECTED:
            raise DefectResolutionControlError("DEFECT_FIX_DETECTED_REQUIRED")
        if not defect.fix_revision:
            raise DefectResolutionControlError("DEFECT_FIX_REVISION_REQUIRED")

        verification_record, verification_evidence = self._passing_execution(
            control,
            verification_artifact_id,
        )
        if verification_record.tc_id not in set(defect.test_case_ids):
            raise DefectResolutionControlError("DEFECT_VERIFICATION_MUST_RUN_ORIGINAL_TEST_CASE")
        if verification_record.attempt_id in set(defect.execution_attempt_ids):
            raise DefectResolutionControlError("DEFECT_VERIFICATION_REQUIRES_NEW_ATTEMPT")

        regressions = tuple(dict.fromkeys(str(value) for value in regression_artifact_ids if str(value)))
        if not regressions:
            raise DefectResolutionControlError("DEFECT_IMPACT_REGRESSION_REQUIRED")
        if verification_artifact_id in regressions:
            raise DefectResolutionControlError("DEFECT_REGRESSION_MUST_BE_DISTINCT_FROM_FIX_VERIFICATION")

        regression_evidence: List[str] = []
        regression_cases = []
        for artifact_id in regressions:
            record, evidence_ids = self._passing_execution(control, artifact_id)
            regression_cases.append(record.tc_id)
            regression_evidence.extend(evidence_ids)

        loop = DefectClosedLoop()
        loop.transition(defect, DefectStatus.VERIFYING)
        loop.transition(
            defect,
            DefectStatus.FIXED,
            verification_refs=[verification_artifact_id],
        )
        loop.transition(defect, DefectStatus.REGRESSION_TESTING)

        task = self._owner_task(control, defect.source_gap_id)
        close_evidence = list(
            dict.fromkeys(
                list(defect.evidence_refs)
                + list(verification_evidence)
                + regression_evidence
            )
        )
        evaluation = Evaluation(
            evaluation_id=self._stable_id(
                "EVAL-DEFECT-CLOSE",
                defect.defect_id,
                defect.fix_revision,
                verification_artifact_id,
                *regressions,
            ),
            mission_id=control.mission_id,
            node="DEFECT",
            artifact_refs=list(task.output_artifact_refs),
            result=EvaluationResult.PASS,
            evaluator_ref=self.CLOSE_EVALUATOR,
            dimensions={
                "defect_id": defect.defect_id,
                "defect_state": DefectStatus.CLOSED.value,
                "fix_revision": defect.fix_revision,
                "fix_verified": True,
                "verification_attempt_id": verification_record.attempt_id,
                "impact_regression_passed": True,
                "regression_case_ids": regression_cases,
            },
            evidence_refs=close_evidence,
        )
        loop.transition(
            defect,
            DefectStatus.CLOSED,
            evaluation_id=evaluation.evaluation_id,
            regression_refs=regressions,
        )
        # Terminal persistence and PRODUCT_DEFECT Gap closure share one control
        # authority.  The control plane writes the Evaluation first, persists the
        # terminal Defect version, accepts the owning Task, then resolves the Gap.
        accepted = control.accept_defect_resolution(
            task.task_id,
            defect=defect,
            evaluation=evaluation,
        )
        gap_row = control.truth.query("rc7_gap", gap_id=defect.source_gap_id)
        if len(gap_row) != 1 or gap_row[0].get("state") != "RESOLVED":
            raise DefectResolutionControlError("PRODUCT_DEFECT_GAP_NOT_RESOLVED")
        return DefectResolutionResult(
            defect_id=defect.defect_id,
            defect_state=defect.state.value,
            fix_revision=defect.fix_revision or "",
            verification_artifact_id=verification_artifact_id,
            regression_artifact_ids=regressions,
            evaluation_id=evaluation.evaluation_id,
            defect_task_state=accepted.state.value,
            product_gap_state=str(gap_row[0]["state"]),
        )

    def reopen_after_failed_verification(
        self,
        control: ClosedLoopControlPlane,
        defect_id: str,
        *,
        failed_execution_artifact_id: str,
    ) -> DefectRecord:
        defect = self._defect(control, defect_id)
        if defect.state != DefectStatus.FIX_DETECTED:
            raise DefectResolutionControlError("DEFECT_FIX_DETECTED_REQUIRED")
        record, evidence_ids = self._execution_record(control, failed_execution_artifact_id)
        if record.integrity_passed is not True or record.status == "PASS":
            raise DefectResolutionControlError("FAILED_FIX_VERIFICATION_EXECUTION_REQUIRED")
        if record.tc_id not in set(defect.test_case_ids):
            raise DefectResolutionControlError("DEFECT_VERIFICATION_MUST_RUN_ORIGINAL_TEST_CASE")
        for evidence_id in evidence_ids:
            if evidence_id not in defect.evidence_refs:
                defect.evidence_refs.append(evidence_id)
        loop = DefectClosedLoop()
        loop.transition(defect, DefectStatus.VERIFYING)
        loop.transition(defect, DefectStatus.REOPENED)
        self._persist_next(control, defect)
        return defect

    def _defect(self, control: ClosedLoopControlPlane, defect_id: str) -> DefectRecord:
        rows = control.truth.query("rc7_defect", defect_id=defect_id)
        if len(rows) != 1:
            raise DefectResolutionControlError("DEFECT_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != control.mission_id:
            raise DefectResolutionControlError("DEFECT_MISSION_MISMATCH")
        hypothesis = row.get("root_cause_hypothesis")
        root = None
        if isinstance(hypothesis, dict):
            root = RootCauseHypothesis(
                hypothesis_id=str(hypothesis["hypothesis_id"]),
                statement=str(hypothesis["statement"]),
                suspected_symbols=tuple(hypothesis.get("suspected_symbols", [])),
                evidence_refs=tuple(hypothesis.get("evidence_refs", [])),
                confidence=float(hypothesis["confidence"]),
            )
        return DefectRecord(
            defect_id=str(row["defect_id"]),
            mission_id=str(row["mission_id"]),
            source_gap_id=str(row["source_gap_id"]),
            requirement_refs=list(row.get("requirement_refs", [])),
            test_case_ids=list(row.get("test_case_ids", [])),
            execution_attempt_ids=list(row.get("execution_attempt_ids", [])),
            expected=row.get("expected"),
            actual=row.get("actual"),
            evidence_refs=list(row.get("evidence_refs", [])),
            severity=str(row.get("severity", "HIGH")),
            state=DefectStatus(str(row["state"])),
            reproduction_attempts=int(row.get("reproduction_attempts", 0)),
            reproduction_passes=int(row.get("reproduction_passes", 0)),
            root_cause_hypothesis=root,
            duplicate_of=row.get("duplicate_of"),
            fix_revision=row.get("fix_revision"),
            verification_refs=list(row.get("verification_refs", [])),
            regression_refs=list(row.get("regression_refs", [])),
            latest_evaluation_id=row.get("latest_evaluation_id"),
            updated_at=int(row.get("updated_at", 0)),
        )

    def _owner_task(self, control: ClosedLoopControlPlane, product_gap_id: str):
        tasks = [
            row
            for row in control.truth.query("rc7_task", mission_id=control.mission_id)
            if row.get("node") == "DEFECT"
            and row.get("task_type") == "QUALIFY_DEFECT"
            and product_gap_id in row.get("gap_refs", [])
        ]
        if len(tasks) != 1:
            raise DefectResolutionControlError("DEFECT_OWNER_TASK_NOT_UNIQUE")
        task = control.scheduler.task(str(tasks[0]["task_id"]))
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise DefectResolutionControlError("DEFECT_OWNER_TASK_OUTPUT_REQUIRED")
        if not task.output_artifact_refs:
            raise DefectResolutionControlError("DEFECT_OWNER_OUTPUT_ARTIFACT_REQUIRED")
        return task

    def _persist_next(self, control: ClosedLoopControlPlane, defect: DefectRecord) -> None:
        rows = control.truth.query("rc7_defect", defect_id=defect.defect_id)
        version = int(rows[0].get("artifact_version", 0)) + 1 if rows else 1
        DefectClosedLoop.persist(
            control.truth,
            release_id=control.release_id,
            defect=defect,
            artifact_version=version,
        )

    def _require_evidence_refs(
        self,
        control: ClosedLoopControlPlane,
        evidence_refs: Iterable[str],
        *,
        defect_id: str,
        required_kind: Optional[str],
    ) -> List[Dict]:
        refs = tuple(dict.fromkeys(str(value) for value in evidence_refs if str(value)))
        if not refs:
            raise DefectResolutionControlError("DEFECT_RESOLUTION_EVIDENCE_REQUIRED")
        rows = []
        for evidence_id in refs:
            found = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(found) != 1 or found[0].get("mission_id") != control.mission_id:
                raise DefectResolutionControlError("DEFECT_RESOLUTION_EVIDENCE_NOT_DURABLE:%s" % evidence_id)
            row = found[0]
            if required_kind is not None and row.get("kind") != required_kind:
                raise DefectResolutionControlError("DEFECT_RESOLUTION_EVIDENCE_KIND_MISMATCH:%s" % evidence_id)
            if defect_id not in set(row.get("subject_refs", [])):
                raise DefectResolutionControlError("DEFECT_RESOLUTION_EVIDENCE_SUBJECT_MISMATCH:%s" % evidence_id)
            rows.append(row)
        return rows

    def _passing_execution(
        self,
        control: ClosedLoopControlPlane,
        artifact_id: str,
    ) -> Tuple[ExecutionRecord, Tuple[str, ...]]:
        record, evidence_ids = self._execution_record(control, artifact_id)
        if record.status != "PASS" or not record.integrity_passed or record.assertion_passed is not True:
            raise DefectResolutionControlError("PASSING_TRUSTED_EXECUTION_REQUIRED:%s" % artifact_id)
        if not record.evidence_refs:
            raise DefectResolutionControlError("EXECUTION_RECORD_EVIDENCE_REQUIRED:%s" % artifact_id)
        return record, evidence_ids

    def _execution_record(
        self,
        control: ClosedLoopControlPlane,
        artifact_id: str,
    ) -> Tuple[ExecutionRecord, Tuple[str, ...]]:
        rows = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise DefectResolutionControlError("EXECUTION_ARTIFACT_NOT_UNIQUE:%s" % artifact_id)
        row = rows[0]
        if row.get("mission_id") != control.mission_id or row.get("artifact_type_name") != "EXECUTION_CONCLUSION":
            raise DefectResolutionControlError("EXECUTION_ARTIFACT_IDENTITY_INVALID:%s" % artifact_id)
        evidence_ids = tuple(row.get("evidence_refs", []))
        if not evidence_ids:
            raise DefectResolutionControlError("EXECUTION_ARTIFACT_EVIDENCE_REQUIRED:%s" % artifact_id)
        for evidence_id in evidence_ids:
            matches = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(matches) != 1 or matches[0].get("mission_id") != control.mission_id:
                raise DefectResolutionControlError("EXECUTION_EVIDENCE_NOT_DURABLE:%s" % evidence_id)
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise DefectResolutionControlError("EXECUTION_RECORD_FILE_REQUIRED:%s" % artifact_id)
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise DefectResolutionControlError("EXECUTION_RECORD_MISSING:%s" % artifact_id)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise DefectResolutionControlError("EXECUTION_RECORD_HASH_MISMATCH:%s" % artifact_id)
        try:
            payload = json.loads(raw.decode("utf-8"))
            item = payload["record"]
            record = ExecutionRecord(
                attempt_id=str(item["attempt_id"]),
                tc_id=str(item["tc_id"]),
                case_version=int(item["case_version"]),
                target_id=str(item["target_id"]),
                layer=str(item["layer"]),
                worker_id=str(item["worker_id"]),
                lease_id=str(item["lease_id"]),
                status=str(item["status"]),
                integrity_passed=bool(item["integrity_passed"]),
                actual_result=item.get("actual_result"),
                tool_call_refs=tuple(item.get("tool_call_refs", [])),
                evidence_refs=tuple(item.get("evidence_refs", [])),
                assertion_ref=item.get("assertion_ref"),
                assertion_passed=item.get("assertion_passed"),
                reason=item.get("reason"),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DefectResolutionControlError("EXECUTION_RECORD_INVALID:%s" % artifact_id) from exc
        return record, evidence_ids

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
        return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])
