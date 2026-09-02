from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts import BusinessJourney, JourneyVerification, RUNTIME_EXECUTIONS
from .errors import R35Error


LIFECYCLE_STAGES = (
    "SOURCE_MAP",
    "RESOLVE_TYPED_KNOWLEDGE",
    "DEFINE_BUSINESS_START_END",
    "ORDER_STEPS_AND_TRANSITIONS",
    "CHECK_EXECUTION_READINESS",
    "CREATE_BOUNDED_WORKSET",
    "EXECUTE_REAL_STEP",
    "OBSERVE_TRANSITION_AND_EVIDENCE",
    "CHECKPOINT_OR_ROTATE_SESSION",
    "REACQUIRE_NEXT_WORKSET",
    "EVALUATE_ORACLES",
    "CLASSIFY_RESULT",
    "ISSUE_JOURNEY_VERIFICATION",
)


@dataclass(frozen=True)
class E2ELifecycle:
    stage: str = "SOURCE_MAP"
    history: tuple[str, ...] = field(default_factory=lambda: ("SOURCE_MAP",))
    field_validation_pending: bool = True

    def __post_init__(self) -> None:
        if self.stage not in LIFECYCLE_STAGES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported E2E lifecycle stage: {self.stage}")
        if not self.history or self.history[0] != "SOURCE_MAP" or self.history[-1] != self.stage:
            raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "E2E lifecycle history is not ordered")
        if any(item not in LIFECYCLE_STAGES for item in self.history):
            raise R35Error("R3_5_SCHEMA_INVALID", "E2E lifecycle history contains an unknown stage")

    def advance(self, stage: str) -> "E2ELifecycle":
        if stage not in LIFECYCLE_STAGES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported E2E lifecycle stage: {stage}")
        expected_index = LIFECYCLE_STAGES.index(self.stage) + 1
        if expected_index >= len(LIFECYCLE_STAGES) or LIFECYCLE_STAGES[expected_index] != stage:
            raise R35Error("R3_5_JOURNEY_ORDER_INVALID", f"cannot advance {self.stage} directly to {stage}")
        return E2ELifecycle(stage=stage, history=self.history + (stage,), field_validation_pending=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "history": list(self.history),
            "field_validation_pending": self.field_validation_pending,
        }


def _oracle_passes(evaluations: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]) -> bool:
    if not evaluations:
        return False
    return all(item.get("result") in {"PASS", "PASSED", True} for item in evaluations)


def classify_execution(
    *,
    journey: BusinessJourney,
    verification_id: str,
    execution_id: str,
    executed_step_refs: tuple[str, ...] | list[str],
    observed_transition_refs: tuple[str, ...] | list[str],
    evidence_refs: tuple[str, ...] | list[str],
    oracle_evaluations: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    runtime_execution: str,
    evidence_class: str = "ENGINEERING_EVIDENCE",
    auth_receipt_refs: tuple[str, ...] | list[str] = (),
    browser_receipt_refs: tuple[str, ...] | list[str] = (),
    source_refs: tuple[Any, ...] | list[Any] = (),
) -> JourneyVerification:
    if runtime_execution not in RUNTIME_EXECUTIONS:
        raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported runtime_execution: {runtime_execution}")
    steps = tuple(str(item) for item in executed_step_refs)
    transitions = tuple(str(item) for item in observed_transition_refs)
    required_steps = set(journey.ordered_step_refs)
    required_transitions = set(journey.ordered_transition_refs)
    def ordered_complete(required: tuple[str, ...], observed: tuple[str, ...]) -> bool:
        position = 0
        for item in observed:
            if position < len(required) and item == required[position]:
                position += 1
        return position == len(required)

    complete = ordered_complete(journey.ordered_step_refs, steps) and ordered_complete(journey.ordered_transition_refs, transitions)
    oracles_pass = _oracle_passes(tuple(dict(item) for item in oracle_evaluations))
    result = "PASS" if complete and oracles_pass else "INCONCLUSIVE"
    verified = (
        runtime_execution == "REAL"
        and evidence_class == "FIELD_EVIDENCE"
        and complete
        and bool(evidence_refs)
        and oracles_pass
    )
    return JourneyVerification(
        verification_id=verification_id,
        journey_id=journey.journey_id,
        journey_version=journey.journey_version,
        execution_id=execution_id,
        executed_step_refs=steps,
        observed_transition_refs=transitions,
        evidence_refs=tuple(str(item) for item in evidence_refs),
        source_refs=tuple(source_refs),
        auth_receipt_refs=tuple(str(item) for item in auth_receipt_refs),
        browser_receipt_refs=tuple(str(item) for item in browser_receipt_refs),
        oracle_evaluations=tuple(dict(item) for item in oracle_evaluations),
        runtime_execution=runtime_execution,
        result=result,
        evidence_class=evidence_class,
        verified_status="VERIFIED" if verified else "NOT_VERIFIED",
    )


def require_engineering_only(verification: JourneyVerification) -> JourneyVerification:
    if verification.evidence_class == "FIELD_EVIDENCE":
        raise R35Error("R3_5_SCHEMA_INVALID", "engineering-only operation cannot accept FIELD_EVIDENCE")
    if verification.verified_status == "VERIFIED":
        raise R35Error("R3_5_VERIFIED_INELIGIBLE", "engineering evidence cannot be VERIFIED")
    return verification


def lifecycle_status(
    *,
    execution_succeeded: bool,
    business_validation_pass: bool,
    field_evidence_available: bool,
) -> str:
    if field_evidence_available and business_validation_pass:
        return "PASSED"
    if business_validation_pass:
        return "INCONCLUSIVE"
    if execution_succeeded:
        return "IN_PROGRESS"
    return "BLOCKED"


def classify_result(verification: JourneyVerification, *, field_evidence_available: bool = False) -> str:
    if verification.verified_status == "VERIFIED":
        return "E2E_VERIFIED"
    if verification.result == "PASS" and field_evidence_available:
        return "BUSINESS_VALIDATION_PASS"
    if verification.runtime_execution == "REAL" and not field_evidence_available:
        return "FIELD_VALIDATION_PENDING"
    if verification.result == "PASS":
        return "BUSINESS_VALIDATION_PASS"
    return "EXECUTION_SUCCEEDED" if verification.runtime_execution in {"REAL", "STRUCTURAL_ONLY", "MOCK", "FAKE"} else "FIELD_VALIDATION_PENDING"
