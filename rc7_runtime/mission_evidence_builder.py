"""R1-derived Mission Evidence Snapshot for RC7 Test Sufficiency.

Mission sufficiency counters are facts, not caller inputs.  This builder derives
its denominator from accepted Test Design obligations/cases and its verified
numerator only from conclusive Execution evaluations backed by immutable runtime
execution artifacts.  Design coverage never becomes runtime verification merely
because a Designer/Reviewer said PASS.

The resulting snapshot is itself an immutable R1 Artifact + Evidence record so
the later MISSION_EVALUATION can reference exactly the truth basis it judged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .mission_sufficiency import MissionEvidenceSnapshot
from .models import Artifact, Evidence
from .truth_overlay import append_entity


class MissionEvidenceBuildError(RuntimeError):
    pass


_OPEN_GAP_STATES = {
    "OPEN", "PLANNED", "REPAIRING", "EVIDENCE_PENDING", "HUMAN_REQUIRED", "BLOCKED",
}
_TERMINAL_DEFECT_STATES = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}
_PENDING_DEFECT_VERIFICATION_STATES = {
    "FIX_DETECTED", "VERIFYING", "FIXED", "REGRESSION_TESTING", "REOPENED",
}
_REQUIREMENT_OBLIGATION_KINDS = {
    "REQUIREMENT_ASSERTION",
    "BUSINESS_RULE",
    "POSITIVE_PATH",
    "NEGATIVE_PATH",
    "BOUNDARY",
    "STATE_TRANSITION",
    "ROLE_PERMISSION",
    "DATA_CONDITION",
    "SIDE_EFFECT",
    "HIGH_RISK_HYPOTHESIS",
}


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _dedupe(values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if isinstance(value, str) and value))


@dataclass(frozen=True)
class BuiltMissionEvidenceSnapshot:
    snapshot: MissionEvidenceSnapshot
    artifact: Artifact
    evidence: Evidence
    basis: Dict[str, Any]


class R1MissionEvidenceSnapshotBuilder:
    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def build(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        producer_task_id: str,
    ) -> BuiltMissionEvidenceSnapshot:
        missions = truth.query("rc7_mission", mission_id=mission_id)
        if len(missions) != 1:
            raise MissionEvidenceBuildError("MISSION_SNAPSHOT_REQUIRES_EXACTLY_ONE_MISSION")
        mission = missions[0]
        release_id = str(mission.get("release_id") or "")
        if not release_id:
            raise MissionEvidenceBuildError("MISSION_SNAPSHOT_RELEASE_ID_REQUIRED")
        if mission.get("residual_risk_ids"):
            # A future ResidualRisk registry can populate the dataclass directly.
            # Until then, never silently treat an unmodelled risk id as accepted.
            raise MissionEvidenceBuildError("MISSION_RESIDUAL_RISK_TRUTH_NOT_MODELLED")

        design_artifact_ids = self._accepted_design_artifacts(truth, mission_id)
        obligations, cases, design_basis = self._design_truth(
            truth,
            mission_id=mission_id,
            artifact_ids=design_artifact_ids,
        )
        executions, execution_basis = self._execution_truth(truth, mission_id=mission_id)

        critical_obligation_ids = {
            oid
            for oid, item in obligations.items()
            if item["required"] and item["risk"] in {"CRITICAL", "HIGH"}
        }
        if not critical_obligation_ids:
            raise MissionEvidenceBuildError("MISSION_CRITICAL_TEST_OBLIGATION_DENOMINATOR_EMPTY")

        requirement_ids = {
            oid
            for oid in critical_obligation_ids
            if obligations[oid]["kind"] in _REQUIREMENT_OBLIGATION_KINDS
        }
        branch_ids = {
            oid
            for oid in critical_obligation_ids
            if obligations[oid]["kind"] == "CODE_IMPACT"
        }

        case_obligations: Dict[str, Set[str]] = {}
        critical_case_ids: Set[str] = set()
        for tc_id, case in cases.items():
            linked = set(case["obligation_ids"])
            case_obligations[tc_id] = linked
            if linked.intersection(critical_obligation_ids):
                critical_case_ids.add(tc_id)

        conclusive_cases = {
            tc_id
            for tc_id, item in executions.items()
            if item["conclusive"] is True
        }
        verified_obligations: Set[str] = set()
        for tc_id in sorted(conclusive_cases):
            verified_obligations.update(case_obligations.get(tc_id, set()))
        verified_obligations.intersection_update(critical_obligation_ids)

        verified_requirements = requirement_ids.intersection(verified_obligations)
        verified_branches = branch_ids.intersection(verified_obligations)
        conclusive_critical_cases = critical_case_ids.intersection(conclusive_cases)

        open_gaps = [
            row
            for row in truth.query("rc7_gap", mission_id=mission_id)
            if row.get("state") in _OPEN_GAP_STATES
            # Prior Mission Evaluation gaps in EVIDENCE_PENDING are awaiting this
            # reevaluation; counting them again would make reevaluation circular.
            and row.get("source_node") != "MISSION_EVALUATION"
        ]
        open_blockers = sorted(
            str(row["gap_id"]) for row in open_gaps if row.get("severity") == "BLOCKER"
        )
        open_critical_gaps = sorted(
            str(row["gap_id"]) for row in open_gaps if row.get("severity") == "CRITICAL"
        )

        defects = truth.query("rc7_defect", mission_id=mission_id)
        open_critical_defects = sorted(
            str(row["defect_id"])
            for row in defects
            if row.get("severity") == "CRITICAL" and row.get("state") not in _TERMINAL_DEFECT_STATES
        )
        open_high_defects = sorted(
            str(row["defect_id"])
            for row in defects
            if row.get("severity") == "HIGH" and row.get("state") not in _TERMINAL_DEFECT_STATES
        )
        pending_defect_verification = sorted(
            str(row["defect_id"])
            for row in defects
            if row.get("state") in _PENDING_DEFECT_VERIFICATION_STATES
        )

        basis = {
            "schema_version": "RC7_MISSION_EVIDENCE_SNAPSHOT_V1",
            "mission_id": mission_id,
            "release_id": release_id,
            "producer_task_id": producer_task_id,
            "design_artifact_ids": sorted(design_artifact_ids),
            "design_basis": design_basis,
            "execution_basis": execution_basis,
            "critical_requirement_refs": sorted(requirement_ids),
            "verified_requirement_refs": sorted(verified_requirements),
            "critical_obligation_refs": sorted(critical_obligation_ids),
            "verified_obligation_refs": sorted(verified_obligations),
            "critical_branch_refs": sorted(branch_ids),
            "verified_branch_refs": sorted(verified_branches),
            "critical_execution_refs": sorted(critical_case_ids),
            "conclusive_execution_refs": sorted(conclusive_critical_cases),
            "open_blocker_gap_refs": open_blockers,
            "open_critical_gap_refs": open_critical_gaps,
            "open_critical_defect_refs": open_critical_defects,
            "open_high_defect_refs": open_high_defects,
            "pending_defect_verification_refs": pending_defect_verification,
        }
        encoded = (json.dumps(basis, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "mission-evidence" / mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("snapshot-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise MissionEvidenceBuildError("MISSION_SNAPSHOT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence_id = _stable_id("EVD-MISSION-SNAPSHOT", mission_id, digest)
        artifact_id = _stable_id("ART-MISSION-SNAPSHOT", mission_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind="MISSION_EVIDENCE_SNAPSHOT",
            source_ref="runtime://mission-evidence-builder",
            content_ref="file://" + str(path),
            subject_refs=[mission_id, producer_task_id, artifact_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=mission_id,
            artifact_type="MISSION_EVIDENCE_SNAPSHOT",
            producer_task_id=producer_task_id,
            content_ref="file://" + str(path),
            parent_refs=sorted(
                set(design_artifact_ids)
                | {
                    artifact_id_value
                    for item in execution_basis
                    for artifact_id_value in item.get("artifact_refs", [])
                }
            ),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        if not truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(truth, evidence, release_id=release_id, artifact_version=1)
        if not truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(truth, artifact, release_id=release_id, artifact_version=1)

        snapshot = MissionEvidenceSnapshot(
            mission_id=mission_id,
            release_id=release_id,
            snapshot_ref=artifact_id,
            evidence_refs=(evidence_id,),
            critical_requirements_total=len(requirement_ids),
            critical_requirements_verified=len(verified_requirements),
            unverified_requirement_refs=tuple(sorted(requirement_ids - verified_requirements)),
            critical_obligations_total=len(critical_obligation_ids),
            critical_obligations_verified=len(verified_obligations),
            unverified_obligation_refs=tuple(sorted(critical_obligation_ids - verified_obligations)),
            critical_branches_total=len(branch_ids),
            critical_branches_verified=len(verified_branches),
            unverified_branch_refs=tuple(sorted(branch_ids - verified_branches)),
            critical_executions_total=len(critical_case_ids),
            critical_executions_conclusive=len(conclusive_critical_cases),
            inconclusive_execution_refs=tuple(sorted(critical_case_ids - conclusive_critical_cases)),
            open_critical_defect_refs=tuple(open_critical_defects),
            open_high_defect_refs=tuple(open_high_defects),
            pending_defect_verification_refs=tuple(pending_defect_verification),
            open_blocker_gap_refs=tuple(open_blockers),
            open_critical_gap_refs=tuple(open_critical_gaps),
            external_blocker_refs=(),
            residual_risks=(),
        )
        return BuiltMissionEvidenceSnapshot(snapshot, artifact, evidence, basis)

    @staticmethod
    def _accepted_design_artifacts(truth: TruthRuntime, mission_id: str) -> Tuple[str, ...]:
        tasks = [
            row
            for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "TEST_DESIGN"
            and row.get("state") == "PASS"
            and row.get("task_type") != "IMPORTED_UPSTREAM_PASS"
        ]
        if not tasks:
            raise MissionEvidenceBuildError("MISSION_ACCEPTED_TEST_DESIGN_REQUIRED")
        artifact_ids: List[str] = []
        for task in tasks:
            evaluation_id = task.get("evaluation_id")
            evaluations = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
            if len(evaluations) != 1 or evaluations[0].get("result") != "PASS":
                raise MissionEvidenceBuildError("MISSION_TEST_DESIGN_PASS_EVALUATION_REQUIRED")
            artifact_ids.extend(str(value) for value in task.get("output_artifact_refs", []) if value)
        if not artifact_ids:
            raise MissionEvidenceBuildError("MISSION_TEST_DESIGN_OUTPUT_REQUIRED")
        return _dedupe(artifact_ids)

    def _design_truth(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        artifact_ids: Sequence[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        obligations: Dict[str, Dict[str, Any]] = {}
        cases: Dict[str, Dict[str, Any]] = {}
        basis: List[Dict[str, Any]] = []
        for artifact_id in artifact_ids:
            row, envelope = self._file_artifact(truth, mission_id, artifact_id, "TEST_DESIGN_MODEL")
            semantic = envelope.get("semantic_payload")
            if not isinstance(semantic, dict):
                raise MissionEvidenceBuildError("MISSION_TEST_DESIGN_SEMANTIC_PAYLOAD_REQUIRED")
            raw_obligations = semantic.get("obligations")
            raw_cases = semantic.get("cases")
            if not isinstance(raw_obligations, list) or not raw_obligations:
                raise MissionEvidenceBuildError("MISSION_TEST_DESIGN_OBLIGATIONS_REQUIRED")
            if not isinstance(raw_cases, list) or not raw_cases:
                raise MissionEvidenceBuildError("MISSION_TEST_DESIGN_CASES_REQUIRED")
            artifact_obligation_ids = []
            artifact_case_ids = []
            for item in raw_obligations:
                if not isinstance(item, dict):
                    raise MissionEvidenceBuildError("MISSION_TEST_OBLIGATION_INVALID")
                oid = str(item.get("obligation_id") or "").strip()
                kind = str(item.get("kind") or "").upper()
                risk = str(item.get("risk") or "").upper()
                if not oid or risk not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} or not kind:
                    raise MissionEvidenceBuildError("MISSION_TEST_OBLIGATION_ID_KIND_RISK_REQUIRED")
                normalized = {
                    "obligation_id": oid,
                    "kind": kind,
                    "risk": risk,
                    "required": item.get("required", True) is True,
                    "artifact_id": artifact_id,
                }
                prior = obligations.get(oid)
                if prior is not None and prior != normalized:
                    raise MissionEvidenceBuildError("MISSION_TEST_OBLIGATION_ID_CONFLICT:%s" % oid)
                obligations[oid] = normalized
                artifact_obligation_ids.append(oid)
            for item in raw_cases:
                if not isinstance(item, dict):
                    raise MissionEvidenceBuildError("MISSION_TEST_CASE_INVALID")
                tc_id = str(item.get("tc_id") or "").strip()
                risk = str(item.get("risk") or "").upper()
                links = item.get("coverage_links")
                if not tc_id or risk not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} or not isinstance(links, list):
                    raise MissionEvidenceBuildError("MISSION_TEST_CASE_ID_RISK_COVERAGE_REQUIRED")
                obligation_ids = []
                for link in links:
                    if not isinstance(link, dict) or not isinstance(link.get("subject_id"), str):
                        raise MissionEvidenceBuildError("MISSION_TEST_CASE_COVERAGE_LINK_INVALID:%s" % tc_id)
                    oid = str(link["subject_id"])
                    if oid not in obligations:
                        raise MissionEvidenceBuildError("MISSION_TEST_CASE_UNKNOWN_OBLIGATION:%s:%s" % (tc_id, oid))
                    obligation_ids.append(oid)
                normalized_case = {
                    "tc_id": tc_id,
                    "risk": risk,
                    "obligation_ids": tuple(dict.fromkeys(obligation_ids)),
                    "artifact_id": artifact_id,
                }
                prior_case = cases.get(tc_id)
                if prior_case is not None and prior_case != normalized_case:
                    raise MissionEvidenceBuildError("MISSION_TEST_CASE_ID_CONFLICT:%s" % tc_id)
                cases[tc_id] = normalized_case
                artifact_case_ids.append(tc_id)
            basis.append(
                {
                    "artifact_id": artifact_id,
                    "content_hash": row.get("content_hash"),
                    "obligation_ids": sorted(artifact_obligation_ids),
                    "case_ids": sorted(artifact_case_ids),
                }
            )
        return obligations, cases, basis

    def _execution_truth(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        evaluations = [
            row
            for row in truth.query("rc7_evaluation", mission_id=mission_id)
            if row.get("node") == "EXECUTION" and row.get("result") == "PASS"
        ]
        by_case: Dict[str, Dict[str, Any]] = {}
        basis: List[Dict[str, Any]] = []
        for evaluation in evaluations:
            dimensions = evaluation.get("dimensions")
            if not isinstance(dimensions, dict) or dimensions.get("conclusive") is not True:
                continue
            refs = evaluation.get("artifact_refs")
            if not isinstance(refs, list) or len(refs) != 1:
                raise MissionEvidenceBuildError("MISSION_EXECUTION_EVALUATION_ARTIFACT_REQUIRED")
            artifact_id = str(refs[0])
            row, payload = self._file_artifact(truth, mission_id, artifact_id, "EXECUTION_CONCLUSION")
            record = payload.get("record")
            if not isinstance(record, dict):
                raise MissionEvidenceBuildError("MISSION_EXECUTION_RECORD_REQUIRED")
            tc_id = str(record.get("tc_id") or "").strip()
            attempt_id = str(record.get("attempt_id") or "").strip()
            if not tc_id or not attempt_id:
                raise MissionEvidenceBuildError("MISSION_EXECUTION_TC_ATTEMPT_REQUIRED")
            if dimensions.get("attempt_id") != attempt_id:
                raise MissionEvidenceBuildError("MISSION_EXECUTION_EVALUATION_ATTEMPT_MISMATCH")
            item = {
                "tc_id": tc_id,
                "attempt_id": attempt_id,
                "evaluation_id": str(evaluation["evaluation_id"]),
                "artifact_refs": [artifact_id],
                "test_result": dimensions.get("test_result"),
                "conclusive": True,
                "content_hash": row.get("content_hash"),
            }
            # Any one trustworthy conclusion is enough to mark this Case as
            # executed/conclusive. Historical FAIL then fixed/PASS attempts stay in
            # R1 and FinalReport; they are not erased here.
            current = by_case.get(tc_id)
            if current is None or str(item["attempt_id"]) > str(current["attempt_id"]):
                by_case[tc_id] = item
            basis.append(item)
        return by_case, basis

    @staticmethod
    def _file_artifact(
        truth: TruthRuntime,
        mission_id: str,
        artifact_id: str,
        expected_type: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_NOT_UNIQUE:%s" % artifact_id)
        row = rows[0]
        if row.get("mission_id") != mission_id or row.get("artifact_type_name") != expected_type:
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_IDENTITY_INVALID:%s" % artifact_id)
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_FILE_REQUIRED:%s" % artifact_id)
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_FILE_MISSING:%s" % artifact_id)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_HASH_MISMATCH:%s" % artifact_id)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_JSON_INVALID:%s" % artifact_id) from exc
        if not isinstance(payload, dict):
            raise MissionEvidenceBuildError("MISSION_ARTIFACT_OBJECT_REQUIRED:%s" % artifact_id)
        return row, payload
