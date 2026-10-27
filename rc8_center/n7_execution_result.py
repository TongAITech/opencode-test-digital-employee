"""Deterministic Center authority for N7 case execution outcomes.

Workers and models may publish runtime observations, but they cannot declare a
case PASS. Center recomputes PASS/FAIL from canonical R1 ASSERTION_OBSERVED
facts, the current N6 assertion denominator, and AVAILABLE evidence manifests.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Sequence, Tuple

from rc8_runtime.contracts import ArtifactAvailability, RuntimeProducerKind

from .executable_readiness import ExecutableReadinessState
from .execution_admission import N7ExecutionAdmission


class N7CaseExecutionResultError(ValueError):
    pass


class N7CaseExecutionOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class N7CaseExecutionResult:
    outcome: N7CaseExecutionOutcome
    test_run_id: str
    work_item_id: str
    case_id: str
    case_execution_attempt_id: str
    prepared_attempt_id: str
    executable_spec_id: str
    assertion_refs: Tuple[str, ...]
    resolved_assertion_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    reason: str


class CenterN7CaseExecutionResultAuthority:
    """Rebuild N7 case outcome from R1 facts plus durable Center authority."""

    ASSERTION_EVENT_TYPE = "ASSERTION_OBSERVED"

    def __init__(
        self,
        *,
        runtime_ledger: object,
        executable_readiness: object,
        artifact_repository: object,
    ) -> None:
        self.runtime_ledger = runtime_ledger
        self.executable_readiness = executable_readiness
        self.artifact_repository = artifact_repository

    def evaluate(self, admission: N7ExecutionAdmission) -> N7CaseExecutionResult:
        if not isinstance(admission, N7ExecutionAdmission):
            raise N7CaseExecutionResultError("N7_EXECUTION_ADMISSION_REQUIRED")

        spec = self.executable_readiness.repository.get_executable_spec(admission.executable_spec_id)
        if spec is None:
            raise N7CaseExecutionResultError("N7_RESULT_EXECUTABLE_SPEC_NOT_FOUND")
        if spec.state != ExecutableReadinessState.READY:
            raise N7CaseExecutionResultError("N7_RESULT_REQUIRES_EXECUTABLE_READY")
        self._validate_spec_identity(spec, admission)

        required = tuple(spec.assertion_refs)
        if not required:
            raise N7CaseExecutionResultError("N7_RESULT_REQUIRES_ASSERTION_DENOMINATOR")
        required_set = set(required)
        allowed_producers = {str(spec.driver_ref)}
        allowed_producers.update(str(value) for value in tuple(spec.evidence_collector_refs or ()))

        observed: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
        events = self.runtime_ledger.runtime_events(
            test_run_id=admission.test_run_id,
            work_item_id=admission.work_item_id,
        )
        for event in events:
            if str(event.get("event_type") or "").strip().upper() != self.ASSERTION_EVENT_TYPE:
                continue
            if str(event.get("case_id") or "") != admission.case_id:
                continue
            if str(event.get("attempt_id") or "") != admission.case_execution_attempt_id:
                continue

            if str(event.get("producer_kind") or "").strip().upper() != RuntimeProducerKind.TOOL.value:
                continue
            producer_ref = str(event.get("producer_ref") or "").strip()
            if producer_ref not in allowed_producers:
                continue

            data = event.get("data")
            if not isinstance(data, dict):
                raise N7CaseExecutionResultError("N7_ASSERTION_OBSERVATION_DATA_REQUIRED")
            assertion_ref = str(data.get("assertion_ref") or "").strip()
            if assertion_ref not in required_set:
                raise N7CaseExecutionResultError(
                    "N7_ASSERTION_NOT_IN_EXECUTABLE_SPEC:%s" % (assertion_ref or "<empty>")
                )
            outcome = str(data.get("outcome") or "").strip().upper()
            if outcome not in {"PASS", "FAIL"}:
                raise N7CaseExecutionResultError(
                    "N7_ASSERTION_OUTCOME_INVALID:%s" % assertion_ref
                )
            evidence_ids = self._evidence_ids(data.get("evidence_refs"))
            if not evidence_ids:
                continue

            node_id = str(event.get("node_id") or "").strip()
            verified_evidence = []
            evidence_pending = False
            for artifact_id in evidence_ids:
                manifest = self.artifact_repository.get(artifact_id)
                if manifest is None or manifest.availability != ArtifactAvailability.AVAILABLE:
                    evidence_pending = True
                    break
                self._validate_evidence_identity(
                    manifest,
                    admission=admission,
                    assertion_ref=assertion_ref,
                    node_id=node_id,
                    allowed_producers=allowed_producers,
                )
                verified_evidence.append(manifest.artifact_id)
            if evidence_pending:
                continue

            current = observed.get(assertion_ref)
            normalized_evidence = tuple(sorted(set(verified_evidence)))
            if current is not None and current[0] != outcome:
                raise N7CaseExecutionResultError(
                    "N7_ASSERTION_OUTCOME_CONFLICT:%s" % assertion_ref
                )
            if current is None:
                observed[assertion_ref] = (outcome, normalized_evidence)
            else:
                observed[assertion_ref] = (
                    outcome,
                    tuple(sorted(set(current[1]).union(normalized_evidence))),
                )

        failed = sorted(ref for ref, value in observed.items() if value[0] == "FAIL")
        resolved = tuple(sorted(observed))
        evidence = tuple(
            sorted(
                {
                    artifact_id
                    for _outcome, evidence_refs in observed.values()
                    for artifact_id in evidence_refs
                }
            )
        )
        if failed:
            return self._result(
                admission,
                required,
                resolved,
                evidence,
                N7CaseExecutionOutcome.FAIL,
                "CENTER_DERIVED_REQUIRED_ASSERTION_FAILED:%s" % ",".join(failed),
            )

        missing = sorted(required_set.difference(observed))
        if missing:
            return self._result(
                admission,
                required,
                resolved,
                evidence,
                N7CaseExecutionOutcome.PENDING,
                "ASSERTION_EVIDENCE_PENDING:%s" % ",".join(missing),
            )

        return self._result(
            admission,
            required,
            resolved,
            evidence,
            N7CaseExecutionOutcome.PASS,
            "CENTER_DERIVED_ALL_REQUIRED_ASSERTIONS_PASSED",
        )

    @staticmethod
    def _evidence_ids(value: object) -> Tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        normalized = []
        for raw in value:
            if not isinstance(raw, str) or not raw.strip():
                return ()
            ref = raw.strip()
            artifact_id = ref.split(":", 1)[1].strip() if ref.startswith("artifact:") else ref
            if not artifact_id:
                return ()
            if artifact_id not in normalized:
                normalized.append(artifact_id)
        return tuple(normalized)

    @staticmethod
    def _validate_spec_identity(spec: object, admission: N7ExecutionAdmission) -> None:
        checks = (
            ("TEST_RUN", getattr(spec, "test_run_id", None), admission.test_run_id),
            ("CASE", getattr(spec, "case_id", None), admission.case_id),
            ("ATTEMPT", getattr(spec, "attempt_id", None), admission.case_execution_attempt_id),
            ("PREPARED_ATTEMPT", getattr(spec, "prepared_attempt_id", None), admission.prepared_attempt_id),
            ("FROZEN_CASE", getattr(spec, "frozen_case_ref", None), admission.frozen_case_ref),
            ("DRIVER", getattr(spec, "driver_ref", None), admission.driver_ref),
        )
        for label, actual, expected in checks:
            if str(actual or "") != str(expected or ""):
                raise N7CaseExecutionResultError("N7_RESULT_%s_AUTHORITY_MISMATCH" % label)

    @staticmethod
    def _validate_evidence_identity(
        manifest: object,
        *,
        admission: N7ExecutionAdmission,
        assertion_ref: str,
        node_id: str,
        allowed_producers: Sequence[str],
    ) -> None:
        checks = (
            ("TEST_RUN", getattr(manifest, "test_run_id", None), admission.test_run_id),
            ("WORK_ITEM", getattr(manifest, "work_item_id", None), admission.work_item_id),
            ("CASE", getattr(manifest, "case_id", None), admission.case_id),
            ("ATTEMPT", getattr(manifest, "attempt_id", None), admission.case_execution_attempt_id),
            ("NODE", getattr(manifest, "node_id", None), node_id),
        )
        for label, actual, expected in checks:
            if str(actual or "") != str(expected or ""):
                raise N7CaseExecutionResultError(
                    "N7_CASE_EXECUTION_EVIDENCE_%s_MISMATCH" % label
                )
        if getattr(manifest, "producer_kind", None) != RuntimeProducerKind.TOOL:
            raise N7CaseExecutionResultError("N7_CASE_EXECUTION_EVIDENCE_TOOL_REQUIRED")
        if str(getattr(manifest, "producer_ref", "") or "") not in set(allowed_producers):
            raise N7CaseExecutionResultError("N7_CASE_EXECUTION_EVIDENCE_PRODUCER_NOT_AUTHORIZED")
        if assertion_ref not in set(getattr(manifest, "refs", ()) or ()):
            raise N7CaseExecutionResultError("N7_CASE_EXECUTION_EVIDENCE_ASSERTION_REF_MISSING")

    @staticmethod
    def _result(
        admission: N7ExecutionAdmission,
        assertion_refs: Sequence[str],
        resolved_assertion_refs: Sequence[str],
        evidence_refs: Sequence[str],
        outcome: N7CaseExecutionOutcome,
        reason: str,
    ) -> N7CaseExecutionResult:
        return N7CaseExecutionResult(
            outcome=outcome,
            test_run_id=admission.test_run_id,
            work_item_id=admission.work_item_id,
            case_id=admission.case_id,
            case_execution_attempt_id=admission.case_execution_attempt_id,
            prepared_attempt_id=admission.prepared_attempt_id,
            executable_spec_id=admission.executable_spec_id,
            assertion_refs=tuple(assertion_refs),
            resolved_assertion_refs=tuple(resolved_assertion_refs),
            evidence_refs=tuple(evidence_refs),
            reason=reason,
        )
