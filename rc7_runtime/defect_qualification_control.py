"""Runtime control for PRODUCT_DEFECT -> Defect candidate qualification.

The qualifier never accepts caller booleans such as `execution_trusted=True`.
It replays the durable RUNTIME_FAILURE_DIAGNOSIS evidence and derives every
qualification predicate from the recorded FailureContext. A separate governed
DEFECT_REPRODUCTION Execution Task supplies reproduction evidence.

The long-lived QUALIFY_DEFECT Task remains OUTPUT_PRODUCED after this stage. It
owns the defect lifecycle until a terminal CLOSED/DUPLICATE/NOT_A_DEFECT
Evaluation is accepted by ClosedLoopControlPlane.accept_defect_resolution().
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rc6_runtime.execution import ExecutionRecord

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import GapRepairPlanner, WorkerOutput
from .defect_loop import (
    DefectClosedLoop,
    DefectQualificationInput,
    DefectRecord,
    DefectStatus,
)
from .defect_reproduction import DefectReproductionResult
from .models import Artifact, Evidence, Gap, GapSeverity, GapStatus, TaskStatus
from .runtime_execution import VerifiedScriptExecutionBundle
from .truth_overlay import append_entity


class DefectQualificationControlError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DefectQualificationRuntimeResult:
    defect_id: str
    defect_state: str
    qualified: bool
    evaluation_id: str
    defect_task_id: str
    defect_task_state: str
    candidate_artifact_id: str
    candidate_evidence_id: str
    qualification_gap_ids: Tuple[str, ...]
    qualification_repair_task_ids: Tuple[str, ...]


class DefectQualificationControl:
    WORKER_REF = "rc7-runtime-defect-qualifier"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).resolve()

    def qualify(
        self,
        control: ClosedLoopControlPlane,
        defect_task_id: str,
        *,
        product_gap_id: str,
        bundle: VerifiedScriptExecutionBundle,
        reproduction: DefectReproductionResult,
        severity: str = "HIGH",
    ) -> DefectQualificationRuntimeResult:
        defect_task = control.scheduler.task(defect_task_id)
        if defect_task.node != "DEFECT" or defect_task.task_type != "QUALIFY_DEFECT":
            raise DefectQualificationControlError("QUALIFY_DEFECT_TASK_REQUIRED")
        if defect_task.state != TaskStatus.READY:
            raise DefectQualificationControlError("QUALIFY_DEFECT_TASK_NOT_READY")
        if defect_task.gap_refs != [product_gap_id]:
            raise DefectQualificationControlError("QUALIFY_DEFECT_GAP_OWNERSHIP_MISMATCH")
        if reproduction.task_state != "PASS" or not reproduction.conclusive:
            raise DefectQualificationControlError("CONCLUSIVE_REPRODUCTION_TASK_PASS_REQUIRED")

        product_gap = self._product_gap(control, product_gap_id)
        original_record, original_artifact_id = self._original_execution_record(control, product_gap_id)
        if original_record.tc_id != bundle.spec.tc_id:
            raise DefectQualificationControlError("DEFECT_SCRIPT_CASE_MISMATCH")
        if original_record.status != "FAIL" or not original_record.integrity_passed or original_record.assertion_passed is not False:
            raise DefectQualificationControlError("DEFECT_REQUIRES_TRUSTED_ORIGINAL_ORACLE_FAIL")

        trust_context, diagnosis_evidence_id = self._trusted_product_context(control, product_gap)
        qualification = self._qualification_from_context(
            trust_context,
            product_gap=product_gap,
            reproduction=reproduction,
        )

        eligible = [
            item
            for item in control.scheduler.ready_tasks(control.mission_id)
            if set(item.required_capabilities).issubset({"defect_analysis"})
        ]
        if not eligible or eligible[0].task_id != defect_task_id:
            raise DefectQualificationControlError("QUALIFY_DEFECT_TASK_NOT_NEXT_READY")
        leased = control.lease_next(
            worker_ref=self.WORKER_REF,
            capabilities=("defect_analysis",),
        )
        if leased is None or leased.task_id != defect_task_id:
            raise DefectQualificationControlError("QUALIFY_DEFECT_LEASE_MISMATCH")
        control.start(defect_task_id, worker_ref=self.WORKER_REF)

        requirement_refs: List[str] = []
        for value in (
            bundle.frozen_case.get("requirement_id"),
            *tuple(bundle.spec.target_requirements),
        ):
            if isinstance(value, str) and value and value not in requirement_refs:
                requirement_refs.append(value)
        expected = bundle.frozen_case.get("expected")
        if expected is None:
            expected = {"oracle": bundle.frozen_case.get("oracle")}

        loop = DefectClosedLoop()
        defect = loop.create_candidate(
            mission_id=control.mission_id,
            product_gap=product_gap,
            requirement_refs=requirement_refs,
            test_case_id=original_record.tc_id,
            execution_attempt_id=original_record.attempt_id,
            expected=expected,
            actual=original_record.actual_result,
            evidence_refs=list(
                dict.fromkeys(
                    list(product_gap.evidence_refs)
                    + list(reproduction.evidence_ids)
                    + [diagnosis_evidence_id]
                )
            ),
            severity=severity,
        )
        loop.transition(defect, DefectStatus.QUALIFYING)

        candidate_artifact, candidate_evidence = self._candidate_output(
            control,
            defect_task_id=defect_task_id,
            defect=defect,
            original_artifact_id=original_artifact_id,
            reproduction_artifact_id=reproduction.record_artifact_id,
            diagnosis_evidence_id=diagnosis_evidence_id,
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=defect_task_id,
                worker_ref=self.WORKER_REF,
                artifacts=(candidate_artifact,),
                evidence=(candidate_evidence,),
            )
        )
        DefectClosedLoop.persist(
            control.truth,
            release_id=control.release_id,
            defect=defect,
            artifact_version=1,
        )

        loop.record_reproduction(
            defect,
            attempt_id=reproduction.execution_record.attempt_id,
            reproduced=bool(reproduction.reproduced),
            evidence_refs=list(reproduction.evidence_ids),
        )
        result = loop.evaluate_qualification(defect, qualification)
        append_entity(
            control.truth,
            result.evaluation,
            release_id=control.release_id,
            artifact_version=1,
        )
        DefectClosedLoop.persist(
            control.truth,
            release_id=control.release_id,
            defect=defect,
            artifact_version=2,
        )

        repair_task_ids = []
        planner = GapRepairPlanner(control.truth, control.release_id, control.scheduler)
        for gap in result.gaps:
            task = planner.plan(gap, priority=30)
            if task is not None:
                repair_task_ids.append(task.task_id)
        if repair_task_ids:
            control.scheduler.refresh_ready(control.mission_id)

        task_after = control.scheduler.task(defect_task_id)
        if task_after.state != TaskStatus.OUTPUT_PRODUCED:
            raise DefectQualificationControlError("QUALIFY_DEFECT_OWNER_TASK_MUST_REMAIN_OUTPUT_PRODUCED")
        return DefectQualificationRuntimeResult(
            defect_id=defect.defect_id,
            defect_state=defect.state.value,
            qualified=result.qualified,
            evaluation_id=result.evaluation.evaluation_id,
            defect_task_id=defect_task_id,
            defect_task_state=task_after.state.value,
            candidate_artifact_id=candidate_artifact.artifact_id,
            candidate_evidence_id=candidate_evidence.evidence_id,
            qualification_gap_ids=tuple(gap.gap_id for gap in result.gaps),
            qualification_repair_task_ids=tuple(repair_task_ids),
        )

    def _product_gap(self, control: ClosedLoopControlPlane, gap_id: str) -> Gap:
        rows = control.truth.query("rc7_gap", gap_id=gap_id)
        if len(rows) != 1:
            raise DefectQualificationControlError("PRODUCT_DEFECT_GAP_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != control.mission_id:
            raise DefectQualificationControlError("PRODUCT_DEFECT_GAP_MISSION_MISMATCH")
        if row.get("category") != "PRODUCT_DEFECT" or row.get("target_node") != "DEFECT":
            raise DefectQualificationControlError("PRODUCT_DEFECT_GAP_REQUIRED")
        return Gap(
            gap_id=str(row["gap_id"]),
            mission_id=str(row["mission_id"]),
            source_node=str(row["source_node"]),
            category=str(row["category"]),
            severity=GapSeverity(str(row["severity"])),
            target_node=str(row["target_node"]),
            description=str(row["description"]),
            state=GapStatus(str(row["state"])),
            subject_refs=list(row.get("subject_refs", [])),
            evidence_refs=list(row.get("evidence_refs", [])),
            root_gap_id=row.get("root_gap_id") if isinstance(row.get("root_gap_id"), str) else None,
            acceptance_criteria=list(row.get("acceptance_criteria", [])),
            resolution_evaluation_id=(
                row.get("resolution_evaluation_id")
                if isinstance(row.get("resolution_evaluation_id"), str)
                else None
            ),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )

    def _original_execution_record(
        self,
        control: ClosedLoopControlPlane,
        product_gap_id: str,
    ) -> Tuple[ExecutionRecord, str]:
        evaluations = [
            row
            for row in control.truth.query("rc7_evaluation", mission_id=control.mission_id)
            if row.get("node") == "EXECUTION"
            and product_gap_id in row.get("gap_refs", [])
            and isinstance(row.get("dimensions"), dict)
            and row["dimensions"].get("failure_class") == "PRODUCT"
            and row["dimensions"].get("test_result") == "FAIL"
        ]
        if len(evaluations) != 1:
            raise DefectQualificationControlError("ORIGINAL_PRODUCT_EVALUATION_NOT_UNIQUE")
        refs = evaluations[0].get("artifact_refs", [])
        if not isinstance(refs, list) or len(refs) != 1:
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_ARTIFACT_REQUIRED")
        artifact_id = str(refs[0])
        artifacts = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifacts) != 1 or artifacts[0].get("artifact_type_name") != "EXECUTION_CONCLUSION":
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_ARTIFACT_NOT_UNIQUE")
        content_ref = artifacts[0].get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_RECORD_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_RECORD_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if artifacts[0].get("content_hash") != "sha256:" + digest:
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_RECORD_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
            record = payload["record"]
            return ExecutionRecord(
                attempt_id=str(record["attempt_id"]),
                tc_id=str(record["tc_id"]),
                case_version=int(record["case_version"]),
                target_id=str(record["target_id"]),
                layer=str(record["layer"]),
                worker_id=str(record["worker_id"]),
                lease_id=str(record["lease_id"]),
                status=str(record["status"]),
                integrity_passed=bool(record["integrity_passed"]),
                actual_result=record.get("actual_result"),
                tool_call_refs=tuple(record.get("tool_call_refs", [])),
                evidence_refs=tuple(record.get("evidence_refs", [])),
                assertion_ref=record.get("assertion_ref"),
                assertion_passed=record.get("assertion_passed"),
                reason=record.get("reason"),
            ), artifact_id
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DefectQualificationControlError("ORIGINAL_EXECUTION_RECORD_INVALID") from exc

    def _trusted_product_context(self, control: ClosedLoopControlPlane, product_gap: Gap) -> Tuple[Dict[str, Any], str]:
        rows = []
        for evidence_id in product_gap.evidence_refs:
            matches = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(matches) == 1 and matches[0].get("kind") == "RUNTIME_FAILURE_DIAGNOSIS":
                rows.append(matches[0])
        if len(rows) != 1:
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_EVIDENCE_NOT_UNIQUE")
        row = rows[0]
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_EVIDENCE_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_EVIDENCE_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_EVIDENCE_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_EVIDENCE_INVALID") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("context"), dict):
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_CONTEXT_REQUIRED")
        diagnosis = payload.get("diagnosis")
        if not isinstance(diagnosis, dict) or diagnosis.get("failure_class") != "PRODUCT":
            raise DefectQualificationControlError("PRODUCT_DIAGNOSIS_CLASS_REQUIRED")
        return payload["context"], str(row["evidence_id"])

    @staticmethod
    def _qualification_from_context(
        context: Dict[str, Any],
        *,
        product_gap: Gap,
        reproduction: DefectReproductionResult,
    ) -> DefectQualificationInput:
        execution_trusted = all(
            bool(context.get(name))
            for name in (
                "preparation_verified",
                "real_action_executed",
                "assertion_failed",
                "case_oracle_verified",
                "executable_spec_verified",
                "script_validated",
                "data_verified",
                "auth_verified",
                "route_verified",
                "tool_verified",
                "environment_verified",
                "dependency_verified",
            )
        )
        evidence_complete = bool(product_gap.evidence_refs) and bool(reproduction.evidence_ids)
        return DefectQualificationInput(
            execution_trusted=execution_trusted,
            oracle_valid=bool(context.get("case_oracle_verified")),
            evidence_complete=evidence_complete,
            script_issue_excluded=bool(context.get("executable_spec_verified")) and bool(context.get("script_validated")),
            data_issue_excluded=bool(context.get("preparation_verified")) and bool(context.get("data_verified")),
            environment_issue_excluded=all(
                bool(context.get(name))
                for name in (
                    "auth_verified",
                    "route_verified",
                    "tool_verified",
                    "environment_verified",
                    "dependency_verified",
                )
            ),
            reproducible=bool(reproduction.reproduced),
        )

    def _candidate_output(
        self,
        control: ClosedLoopControlPlane,
        *,
        defect_task_id: str,
        defect: DefectRecord,
        original_artifact_id: str,
        reproduction_artifact_id: str,
        diagnosis_evidence_id: str,
    ) -> Tuple[Artifact, Evidence]:
        folder = self.evidence_root / "defect-candidates" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (defect.defect_id + ".json")
        payload = {
            "defect": asdict(defect),
            "original_execution_artifact_id": original_artifact_id,
            "reproduction_execution_artifact_id": reproduction_artifact_id,
            "diagnosis_evidence_id": diagnosis_evidence_id,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        path.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        evidence = Evidence(
            evidence_id=_stable_id("EVD-DEFECT-CANDIDATE", control.mission_id, defect.defect_id, digest),
            mission_id=control.mission_id,
            kind="DEFECT_CANDIDATE_RECORD",
            source_ref="runtime://defect-qualification",
            content_ref="file://" + str(path),
            subject_refs=[defect_task_id, defect.defect_id, defect.source_gap_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=_stable_id("ART-DEFECT-CANDIDATE", control.mission_id, defect.defect_id, digest),
            mission_id=control.mission_id,
            artifact_type="DEFECT_CANDIDATE",
            producer_task_id=defect_task_id,
            content_ref="file://" + str(path),
            parent_refs=[original_artifact_id, reproduction_artifact_id],
            evidence_refs=list(dict.fromkeys(defect.evidence_refs + [evidence.evidence_id])),
            content_hash="sha256:" + digest,
        )
        return artifact, evidence
