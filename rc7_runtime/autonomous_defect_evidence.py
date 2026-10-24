"""RC7.1 N9 evidence closure from qualified defect to independent review.

Qualification/reproduction remain Runtime-owned elsewhere. This service starts
only from durable EVIDENCE_READY defect truth, derives signature/severity/RCA
from current evidence, compares prior defect packages, and publishes a durable
N9 evidence package. It never CONFIRMS, DUPLICATES, FILES or CLOSES a defect;
those decisions remain independent review / governed side effects.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .defect_evidence_policy import (
    DefectEvidencePolicy,
    DefectSignature,
    DuplicateDecision,
    RCAAssessment,
    RCAEvidenceChain,
    SeverityDecision,
    SeverityFactors,
)
from .defect_loop import (
    DefectClosedLoop,
    DefectRecord,
    DefectStatus,
    RootCauseHypothesis,
)
from .models import Artifact, Evidence, TaskStatus
from .truth_overlay import append_entity


class N9DefectEvidenceError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise N9DefectEvidenceError(code)
    return text


@dataclass(frozen=True)
class N9DefectEvidenceReceipt:
    defect_id: str
    defect_state: str
    defect_signature_id: str
    severity: str
    severity_score: int
    rca_level: str
    duplicate_disposition: str
    duplicate_of_candidate: Optional[str]
    package_artifact_id: str
    package_evidence_id: str
    package_sha256: str


class AutonomousDefectEvidenceService:
    PACKAGE_TYPE = "N9_DEFECT_EVIDENCE_PACKAGE"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def prepare_for_review(
        self,
        control: ClosedLoopControlPlane,
        *,
        defect_task_id: str,
        defect_id: str,
        signature: DefectSignature,
        severity_factors: SeverityFactors,
        rca_chain: RCAEvidenceChain,
    ) -> N9DefectEvidenceReceipt:
        task = control.scheduler.task(defect_task_id)
        if task.node != "DEFECT" or task.task_type != "QUALIFY_DEFECT":
            raise N9DefectEvidenceError("N9_QUALIFY_DEFECT_TASK_REQUIRED")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise N9DefectEvidenceError("N9_DEFECT_OWNER_OUTPUT_PRODUCED_REQUIRED")

        row = self._one(
            control,
            "rc7_defect",
            "defect_id",
            defect_id,
            "N9_DEFECT_NOT_UNIQUE",
        )
        if row.get("mission_id") != control.mission_id:
            raise N9DefectEvidenceError("N9_DEFECT_MISSION_MISMATCH")
        defect = self._rehydrate_defect(row)
        if defect.state != DefectStatus.EVIDENCE_READY:
            raise N9DefectEvidenceError("N9_DEFECT_EVIDENCE_READY_REQUIRED")
        if task.gap_refs != [defect.source_gap_id]:
            raise N9DefectEvidenceError("N9_DEFECT_TASK_GAP_OWNERSHIP_MISMATCH")
        gap = self._one(
            control,
            "rc7_gap",
            "gap_id",
            defect.source_gap_id,
            "N9_PRODUCT_GAP_NOT_UNIQUE",
        )
        if gap.get("category") != "PRODUCT_DEFECT" or gap.get("target_node") != "DEFECT":
            raise N9DefectEvidenceError("N9_PRODUCT_DEFECT_GAP_REQUIRED")

        if not set(defect.requirement_refs).intersection(signature.requirement_refs):
            raise N9DefectEvidenceError("N9_SIGNATURE_REQUIREMENT_TRACE_MISMATCH")
        all_evidence = tuple(
            dict.fromkeys(
                tuple(signature.evidence_refs)
                + tuple(severity_factors.evidence_refs)
                + tuple(rca_chain.symptom_evidence_refs)
                + tuple(rca_chain.evidence_refs)
            )
        )
        self._require_durable_evidence(control, all_evidence)

        severity = DefectEvidencePolicy.derive_severity(severity_factors)
        rca = DefectEvidencePolicy.assess_rca(rca_chain)
        if not rca.filing_minimum_met:
            raise N9DefectEvidenceError("N9_RCA_FILING_MINIMUM_NOT_MET:%s" % rca.level)
        duplicate = self._best_duplicate_decision(
            control,
            defect_id=defect.defect_id,
            candidate=signature,
        )

        hypothesis = self._root_cause_hypothesis(
            defect=defect,
            signature=signature,
            rca=rca,
            chain=rca_chain,
        )
        defect.severity = severity.severity
        for evidence_id in all_evidence:
            if evidence_id not in defect.evidence_refs:
                defect.evidence_refs.append(evidence_id)
        DefectClosedLoop.attach_root_cause_hypothesis(defect, hypothesis)
        DefectClosedLoop().transition(defect, DefectStatus.READY_FOR_REVIEW)

        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "defect_task_id": defect_task_id,
            "defect_id": defect.defect_id,
            "source_gap_id": defect.source_gap_id,
            "defect_state": defect.state.value,
            "filing_ready": True,
            "signature": asdict(signature),
            "severity_decision": asdict(severity),
            "rca_assessment": asdict(rca),
            "duplicate_decision": asdict(duplicate),
            "root_cause_hypothesis": asdict(hypothesis),
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n9-defects" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (defect.defect_id + "-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise N9DefectEvidenceError("N9_DEFECT_PACKAGE_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence_id = _stable_id("EVD-N9-DEFECT", defect.defect_id, digest)
        artifact_id = _stable_id("ART-N9-DEFECT", defect.defect_id, digest)
        package_evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.PACKAGE_TYPE,
            source_ref="runtime://n9-defect-evidence",
            content_ref="file://" + str(path),
            subject_refs=[
                defect.defect_id,
                defect.source_gap_id,
                signature.signature_id,
                severity.severity,
                rca.level,
                duplicate.disposition,
            ],
            content_hash="sha256:" + digest,
        )
        package_artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.PACKAGE_TYPE,
            producer_task_id=defect_task_id,
            content_ref="file://" + str(path),
            parent_refs=list(task.output_artifact_refs),
            evidence_refs=[evidence_id] + list(all_evidence),
            content_hash="sha256:" + digest,
        )
        append_entity(control.truth, package_evidence, release_id=control.release_id)
        append_entity(control.truth, package_artifact, release_id=control.release_id)
        if evidence_id not in defect.evidence_refs:
            defect.evidence_refs.append(evidence_id)

        next_version = int(row.get("artifact_version", 0)) + 1
        DefectClosedLoop.persist(
            control.truth,
            release_id=control.release_id,
            defect=defect,
            artifact_version=next_version,
        )
        return N9DefectEvidenceReceipt(
            defect_id=defect.defect_id,
            defect_state=defect.state.value,
            defect_signature_id=signature.signature_id,
            severity=severity.severity,
            severity_score=severity.score,
            rca_level=rca.level,
            duplicate_disposition=duplicate.disposition,
            duplicate_of_candidate=duplicate.matched_defect_id,
            package_artifact_id=artifact_id,
            package_evidence_id=evidence_id,
            package_sha256=digest,
        )

    def _best_duplicate_decision(
        self,
        control: ClosedLoopControlPlane,
        *,
        defect_id: str,
        candidate: DefectSignature,
    ) -> DuplicateDecision:
        priority = {"DISTINCT": 0, "POSSIBLE_DUPLICATE": 1, "DUPLICATE": 2}
        best = DuplicateDecision(
            disposition="DISTINCT",
            confidence=0.0,
            matched_defect_id=None,
            matched_fields=(),
            reason="NO_PRIOR_COMPATIBLE_DEFECT_PACKAGE",
        )
        rows = [
            row
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == self.PACKAGE_TYPE
            and defect_id not in set(str(x) for x in row.get("subject_refs", []))
        ]
        for row in rows:
            existing_defect_id, existing_signature = self._load_prior_package(row)
            decision = DefectEvidencePolicy.compare(
                candidate,
                existing_defect_id,
                existing_signature,
            )
            if priority[decision.disposition] > priority[best.disposition]:
                best = decision
            elif (
                priority[decision.disposition] == priority[best.disposition]
                and decision.confidence > best.confidence
            ):
                best = decision
        return best

    def _load_prior_package(self, row: Mapping[str, object]) -> Tuple[str, DefectSignature]:
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise N9DefectEvidenceError("N9_PRIOR_PACKAGE_CONTENT_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise N9DefectEvidenceError("N9_PRIOR_PACKAGE_CONTENT_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise N9DefectEvidenceError("N9_PRIOR_PACKAGE_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
            defect_id = _required(payload.get("defect_id"), "N9_PRIOR_PACKAGE_DEFECT_ID_REQUIRED")
            raw_signature = payload["signature"]
            signature = DefectSignature(
                signature_id=str(raw_signature["signature_id"]),
                product_area=str(raw_signature["product_area"]),
                requirement_refs=tuple(raw_signature.get("requirement_refs", [])),
                affected_application=str(raw_signature["affected_application"]),
                surface_ref=str(raw_signature.get("surface_ref") or ""),
                failure_signature_id=str(raw_signature["failure_signature_id"]),
                business_error_code=raw_signature.get("business_error_code"),
                root_stack_frame=raw_signature.get("root_stack_frame"),
                suspected_symbols=tuple(raw_signature.get("suspected_symbols", [])),
                codegraph_root=raw_signature.get("codegraph_root"),
                business_symptom=str(raw_signature["business_symptom"]),
                final_state_mismatch=raw_signature.get("final_state_mismatch"),
                root_cause_statement=raw_signature.get("root_cause_statement"),
                evidence_refs=tuple(raw_signature.get("evidence_refs", [])),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise N9DefectEvidenceError("N9_PRIOR_PACKAGE_CONTENT_INVALID") from exc
        return defect_id, signature

    @staticmethod
    def _root_cause_hypothesis(
        *,
        defect: DefectRecord,
        signature: DefectSignature,
        rca: RCAAssessment,
        chain: RCAEvidenceChain,
    ) -> RootCauseHypothesis:
        statement = str(signature.root_cause_statement or "").strip()
        if not statement:
            if rca.level_number >= 3 and chain.module_or_symbol:
                statement = "evidence-backed suspected root cause at %s: %s" % (
                    rca.level,
                    chain.module_or_symbol,
                )
            else:
                statement = "evidence-backed RCA scope at %s: %s / %s" % (
                    rca.level,
                    chain.affected_application,
                    chain.service_or_endpoint,
                )
        evidence = tuple(
            dict.fromkeys(
                tuple(signature.evidence_refs)
                + tuple(chain.symptom_evidence_refs)
                + tuple(chain.evidence_refs)
            )
        )
        confidence = {2: 0.55, 3: 0.70, 4: 0.85}.get(rca.level_number, 0.50)
        return RootCauseHypothesis(
            hypothesis_id=_stable_id(
                "RCA-HYP",
                defect.defect_id,
                signature.signature_id,
                rca.level,
                statement,
            ),
            statement=statement,
            suspected_symbols=tuple(signature.suspected_symbols),
            evidence_refs=evidence,
            confidence=confidence,
        )

    @staticmethod
    def _rehydrate_defect(row: Mapping[str, object]) -> DefectRecord:
        raw_hypothesis = row.get("root_cause_hypothesis")
        hypothesis = None
        if isinstance(raw_hypothesis, dict):
            hypothesis = RootCauseHypothesis(
                hypothesis_id=str(raw_hypothesis["hypothesis_id"]),
                statement=str(raw_hypothesis["statement"]),
                suspected_symbols=tuple(raw_hypothesis.get("suspected_symbols", [])),
                evidence_refs=tuple(raw_hypothesis.get("evidence_refs", [])),
                confidence=float(raw_hypothesis["confidence"]),
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
            severity=str(row.get("severity") or "HIGH"),
            state=DefectStatus(str(row["state"])),
            reproduction_attempts=int(row.get("reproduction_attempts", 0)),
            reproduction_passes=int(row.get("reproduction_passes", 0)),
            root_cause_hypothesis=hypothesis,
            duplicate_of=(str(row["duplicate_of"]) if row.get("duplicate_of") else None),
            fix_revision=(str(row["fix_revision"]) if row.get("fix_revision") else None),
            verification_refs=list(row.get("verification_refs", [])),
            regression_refs=list(row.get("regression_refs", [])),
            latest_evaluation_id=(
                str(row["latest_evaluation_id"]) if row.get("latest_evaluation_id") else None
            ),
            updated_at=int(row.get("updated_at", 0)),
        )

    @staticmethod
    def _require_durable_evidence(
        control: ClosedLoopControlPlane,
        evidence_refs: Sequence[str],
    ) -> None:
        if not evidence_refs:
            raise N9DefectEvidenceError("N9_CURRENT_EVIDENCE_REQUIRED")
        for evidence_id in evidence_refs:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                raise N9DefectEvidenceError("N9_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
            if rows[0].get("mission_id") != control.mission_id:
                raise N9DefectEvidenceError("N9_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)

    @staticmethod
    def _one(
        control: ClosedLoopControlPlane,
        entity_type: str,
        field: str,
        value: str,
        code: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query(entity_type, **{field: value})
        if len(rows) != 1:
            raise N9DefectEvidenceError(code)
        return rows[0]
