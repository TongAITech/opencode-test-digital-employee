"""RC7.1 N6 semantic script closure over the existing Runtime readiness gate.

The existing DshScriptReadinessEvaluator remains authoritative for source
persistence, compile/discovery/dependency readiness and frozen Case/Oracle
fingerprints.  This module adds the autonomous-node semantic closure that was
missing: every executable Case action, Oracle reference, runtime binding and
evidence requirement must be mapped to an implementation point before N6 can
publish a NodeDeliveryPackage.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping, Sequence, Tuple

from rc6_runtime.executable_spec import ExecutableTestSpec

from .autonomous_node_control import NodeDeliveryReceipt
from .autonomous_preparation_node import WaveCNodeAdoptionControl
from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evidence, Gap, GapSeverity
from .truth_overlay import append_entity


class AutonomousScriptNodeError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class AutonomousScriptNodeService:
    MATRIX_EVIDENCE_KIND = "SCRIPT_IMPLEMENTATION_MATRIX_VERIFIED"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = str(evidence_root)
        self.reader = CandidatePayloadReader()

    def publish_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        task_id: str,
        artifact_id: str,
        spec: ExecutableTestSpec,
        team_id: str = "",
        assignment_ids: Sequence[str] = (),
        member_ids: Sequence[str] = (),
    ) -> NodeDeliveryReceipt:
        run_id = self._required(run_id, "N6_RUN_ID_REQUIRED")
        task = self._one(control, "rc7_task", "task_id", task_id, "N6_SOURCE_TASK_NOT_UNIQUE")
        if task.get("mission_id") != control.mission_id or task.get("node") != "SCRIPT_READINESS":
            raise AutonomousScriptNodeError("N6_SCRIPT_TASK_REQUIRED")
        if task.get("state") != "PASS":
            raise AutonomousScriptNodeError("N6_SCRIPT_READINESS_PASS_REQUIRED")
        evaluation_id = self._required(task.get("evaluation_id"), "N6_SCRIPT_EVALUATION_REQUIRED")
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "N6_SCRIPT_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("mission_id") != control.mission_id or evaluation.get("node") != "SCRIPT_READINESS":
            raise AutonomousScriptNodeError("N6_SCRIPT_EVALUATION_IDENTITY_MISMATCH")
        if evaluation.get("result") != "PASS" or list(evaluation.get("gap_refs") or []):
            raise AutonomousScriptNodeError("N6_SCRIPT_SUFFICIENCY_PASS_REQUIRED")
        dimensions = evaluation.get("dimensions") or {}
        if dimensions.get("business_assertion_executed") is not False:
            raise AutonomousScriptNodeError("N6_BUSINESS_ASSERTION_MUST_NOT_EXECUTE")
        if dimensions.get("case_fingerprint") != spec.case_fingerprint:
            raise AutonomousScriptNodeError("N6_CASE_FINGERPRINT_MISMATCH")
        if dimensions.get("oracle_fingerprint") != spec.oracle_fingerprint:
            raise AutonomousScriptNodeError("N6_ORACLE_FINGERPRINT_MISMATCH")

        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        matrix = candidate.semantic_payload.get("implementation_matrix")
        issues = self._matrix_issues(matrix, spec)
        adoption = WaveCNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=self.evidence_root,
        )
        input_version = "%s|%s|%s|%s" % (
            spec.spec_id,
            spec.case_fingerprint,
            spec.oracle_fingerprint,
            candidate.content_hash,
        )
        delta_hash = "sha256:" + hashlib.sha256(
            (input_version + "|" + ",".join(sorted(issues))).encode("utf-8")
        ).hexdigest()
        iteration = adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N6",
            input_version=input_version,
            delta_hash=delta_hash,
        )

        candidate_row = self._one(control, "rc7_artifact", "artifact_id", artifact_id, "N6_CANDIDATE_ARTIFACT_NOT_UNIQUE")
        candidate_evidence = tuple(dict.fromkeys(
            str(x) for x in candidate_row.get("evidence_refs") or [] if str(x)
        ))
        if not candidate_evidence:
            raise AutonomousScriptNodeError("N6_CANDIDATE_EVIDENCE_REQUIRED")
        for evidence_id in candidate_evidence:
            evidence = self._one(control, "rc7_evidence", "evidence_id", evidence_id, "N6_CANDIDATE_EVIDENCE_NOT_UNIQUE")
            if evidence.get("mission_id") != control.mission_id:
                raise AutonomousScriptNodeError("N6_CANDIDATE_EVIDENCE_MISSION_MISMATCH")

        if issues:
            gap_id = _stable_id(
                "GAP-N6-SEMANTIC",
                control.mission_id,
                task_id,
                artifact_id,
                *sorted(issues),
            )
            gap = Gap(
                gap_id=gap_id,
                mission_id=control.mission_id,
                source_node="SCRIPT_READINESS",
                category="SCRIPT_IMPLEMENTATION_COVERAGE_GAP",
                severity=GapSeverity.HIGH,
                target_node="SCRIPT_READINESS",
                description=";".join(sorted(issues)),
                subject_refs=[task_id, artifact_id, spec.spec_id, spec.tc_id],
                evidence_refs=list(candidate_evidence),
                acceptance_criteria=[
                    "every Case action maps to one executable implementation reference",
                    "every frozen Oracle reference maps to one assertion/runtime Oracle hook",
                    "every runtime binding maps to one injection point",
                    "every evidence requirement maps to one evidence collector",
                ],
            )
            if not control.truth.query("rc7_gap", gap_id=gap_id):
                append_entity(control.truth, gap, release_id=control.release_id)
            adoption.node_control.record_gap_detected(
                iteration,
                gap_ids=[gap_id],
                evidence_refs=list(candidate_evidence),
            )
            raise AutonomousScriptNodeError("N6_SEMANTIC_IMPLEMENTATION_INCOMPLETE:%s" % gap_id)

        matrix_evidence_id = _stable_id(
            "EVD-N6-MATRIX",
            control.mission_id,
            artifact_id,
            spec.spec_id,
            candidate.content_hash,
        )
        if not control.truth.query("rc7_evidence", evidence_id=matrix_evidence_id):
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=matrix_evidence_id,
                    mission_id=control.mission_id,
                    kind=self.MATRIX_EVIDENCE_KIND,
                    source_ref="runtime://script-semantic-gate",
                    content_ref=candidate.content_ref,
                    subject_refs=[task_id, artifact_id, spec.spec_id, spec.tc_id],
                    content_hash=candidate.content_hash,
                ),
                release_id=control.release_id,
            )

        evaluation_evidence = tuple(dict.fromkeys(
            str(x) for x in evaluation.get("evidence_refs") or [] if str(x)
        ))
        delivery_evidence = tuple(dict.fromkeys(
            list(candidate_evidence) + list(evaluation_evidence) + [matrix_evidence_id]
        ))
        for evidence_id in delivery_evidence:
            row = self._one(control, "rc7_evidence", "evidence_id", evidence_id, "N6_DELIVERY_EVIDENCE_NOT_UNIQUE")
            if row.get("mission_id") != control.mission_id:
                raise AutonomousScriptNodeError("N6_DELIVERY_EVIDENCE_MISSION_MISMATCH")

        return adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=[artifact_id],
            evidence_refs=list(delivery_evidence),
            team_id=team_id,
            assignment_ids=assignment_ids,
            member_ids=member_ids,
            coverage_summary={
                "case_step_implementation": "100%",
                "oracle_implementation": "100%",
                "runtime_binding_implementation": "100%",
                "evidence_collector_implementation": "100%",
            },
            reviewer_result={
                "result": "PASS",
                "runtime_readiness_evaluator": evaluation.get("evaluator_ref"),
                "semantic_matrix_evaluator": "rc7-runtime-script-semantic-gate",
            },
            sufficiency_result={
                "result": "PASS",
                "technical_readiness": "PASS",
                "semantic_implementation_readiness": "PASS",
                "business_assertion_executed": False,
                "spec_id": spec.spec_id,
                "tc_id": spec.tc_id,
                "case_fingerprint": spec.case_fingerprint,
                "oracle_fingerprint": spec.oracle_fingerprint,
            },
        )

    @staticmethod
    def _matrix_issues(raw: Any, spec: ExecutableTestSpec) -> Tuple[str, ...]:
        if not isinstance(raw, Mapping):
            return ("SCRIPT_IMPLEMENTATION_MATRIX_REQUIRED",)
        issues = []
        expected = {
            "steps": {str(index) for index in range(1, len(spec.ordered_actions) + 1)},
            "oracles": set(spec.oracle_refs),
            "runtime_bindings": set(
                [str(item.get("id")) for item in spec.preconditions if isinstance(item, Mapping) and item.get("id")]
                + list(spec.test_data_refs)
            ),
            "evidence_collectors": set(spec.evidence_requirements),
        }
        definitions = {
            "steps": ("order", "implementation_ref"),
            "oracles": ("oracle_ref", "assertion_ref"),
            "runtime_bindings": ("binding_ref", "injection_ref"),
            "evidence_collectors": ("requirement", "collector_ref"),
        }
        for section, wanted in expected.items():
            rows = raw.get(section)
            if not isinstance(rows, list):
                issues.append("SCRIPT_MATRIX_SECTION_REQUIRED:%s" % section)
                continue
            key_field, impl_field = definitions[section]
            seen = []
            invalid_impl = False
            for row in rows:
                if not isinstance(row, Mapping):
                    issues.append("SCRIPT_MATRIX_ROW_INVALID:%s" % section)
                    continue
                key = row.get(key_field)
                if section == "steps" and isinstance(key, int):
                    key = str(key)
                elif isinstance(key, str):
                    key = key.strip()
                else:
                    key = ""
                implementation = row.get(impl_field)
                if not key:
                    issues.append("SCRIPT_MATRIX_KEY_REQUIRED:%s" % section)
                    continue
                seen.append(key)
                if not isinstance(implementation, str) or not implementation.strip():
                    invalid_impl = True
            if invalid_impl:
                issues.append("SCRIPT_MATRIX_IMPLEMENTATION_REF_REQUIRED:%s" % section)
            if len(seen) != len(set(seen)):
                issues.append("SCRIPT_MATRIX_DUPLICATE_MAPPING:%s" % section)
            actual = set(seen)
            missing = sorted(wanted - actual)
            unexpected = sorted(actual - wanted)
            if missing:
                issues.append("SCRIPT_MATRIX_MISSING:%s:%s" % (section, ",".join(missing)))
            if unexpected:
                issues.append("SCRIPT_MATRIX_UNEXPECTED:%s:%s" % (section, ",".join(unexpected)))
        return tuple(sorted(set(issues)))

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
            raise AutonomousScriptNodeError(code)
        return rows[0]

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise AutonomousScriptNodeError(code)
        return text
