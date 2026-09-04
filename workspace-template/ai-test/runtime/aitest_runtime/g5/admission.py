"""Exact, non-durable admission of governed G4 observations into G5."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..durable_core import RuntimeError, RuntimeService, canonical_sha256
from ..g3.contracts import EXTENSION_ID as G3_EXTENSION_ID
from ..g4.contracts import EXTENSION_ID as G4_EXTENSION_ID, G4Fact
from ..r4_1.contracts import EXTENSION_ID as R41_EXTENSION_ID
from .contracts import G4ObservationAdmission


_G4_ORACLE_TRIGGERS = frozenset({"FAIL", "ERROR", "INCONCLUSIVE"})


def _fail(code: str, message: str, **details: Any) -> None:
    raise RuntimeError(code, message, details)


def _text(value: Any, name: str, code: str = "G5_G4_LINEAGE_MISSING") -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{name} is required", field=name)
    return value.strip()


def _fact_ref(fact: Any) -> dict[str, Any]:
    return {"ref_id": fact.fact_id, "digest": fact.digest, "fact_kind": fact.fact_kind}


def _derived_ref(ref_id: str, value: Any, *, ref_kind: str) -> dict[str, Any]:
    return {
        "ref_id": ref_id,
        "digest": canonical_sha256({"ref_kind": ref_kind, "value": value}),
        "ref_kind": ref_kind,
    }


def _r41_ref(entity: Any, *, ref_kind: str, identity_name: str, digest_name: str) -> dict[str, Any]:
    return {
        identity_name: getattr(entity, identity_name),
        "digest": getattr(entity, digest_name),
        "ref_kind": ref_kind,
    }


def _require_exact_supplied_fact(
    supplied: Mapping[str, Any],
    durable: G4Fact,
    *,
    mission_id: str,
) -> None:
    if (
        supplied.get("fact_id") != durable.fact_id
        or supplied.get("digest") != durable.digest
        or supplied.get("mission_id") != mission_id
        or supplied.get("fact_kind") != durable.fact_kind
        or supplied.get("payload") != durable.payload
        or tuple(supplied.get("provenance_refs") or ()) != durable.provenance_refs
    ):
        _fail(
            "G5_G4_ADMISSION_INVALID",
            "Supplied G4 observation is not the exact durable same-Mission fact",
            observation_ref=str(supplied.get("fact_id") or ""),
        )


@dataclass(frozen=True)
class AdmittedG4Observation:
    """Internal source objects plus the public non-durable admission envelope."""

    admission: G4ObservationAdmission
    observation: G4Fact
    step_result: G4Fact
    goal: G4Fact
    execution_batch: G4Fact
    step_cursor: G4Fact


def admit_g4_observation(
    runtime: RuntimeService,
    *,
    mission_id: str,
    observation_ref: Any,
) -> AdmittedG4Observation:
    """Resolve and validate the exact G4/G3/R4.1 lineage without writing truth."""

    if not isinstance(observation_ref, Mapping) or not observation_ref:
        _fail("G5_G4_LINEAGE_MISSING", "g4_observation_ref must identify an exact durable G4 fact")

    composed = runtime.replay_composed(mission_id)
    g4 = composed.extension_state(G4_EXTENSION_ID)
    g3 = composed.extension_state(G3_EXTENSION_ID)
    r41 = composed.extension_state(R41_EXTENSION_ID)
    execution = composed.extension_state("r1_3b_execution_resume")
    if g4 is None or g3 is None or r41 is None or execution is None:
        _fail("G5_G4_LINEAGE_MISSING", "Required G4/G3/R4.1/execution lineage is unavailable")

    observation_id = _text(observation_ref.get("fact_id"), "g4_observation_ref.fact_id")
    observation = g4.by_id(observation_id) if hasattr(g4, "by_id") else None
    if observation is None:
        _fail("G5_G4_LINEAGE_MISSING", "G4 observation does not exist", observation_ref=observation_id)
    _require_exact_supplied_fact(observation_ref, observation, mission_id=mission_id)
    if observation.fact_kind != "UNEXPECTED_OBSERVATION":
        _fail("G5_G4_ADMISSION_INVALID", "G4 fact is not UNEXPECTED_OBSERVATION")

    observation_payload = dict(observation.payload)
    trigger = str(observation_payload.get("oracle_result") or "").upper()
    if (
        observation_payload.get("status") != "OBSERVATION_ONLY"
        or observation_payload.get("g5_defect_truth") != "HOLD"
        or trigger not in _G4_ORACLE_TRIGGERS
    ):
        _fail("G5_G4_ADMISSION_INVALID", "G4 observation is not an eligible observation-only trigger")

    step_result_id = _text(observation_payload.get("step_result_ref"), "observation.step_result_ref")
    if observation.provenance_refs != (step_result_id,):
        _fail("G5_G4_LINEAGE_MISSING", "Observation provenance does not exactly identify its step result")
    step_result = g4.by_id(step_result_id)
    if (
        step_result is None
        or step_result.fact_kind != "EXECUTION_STEP_RESULT"
        or step_result.mission_id != mission_id
        or str(step_result.payload.get("oracle_result") or "").upper() != trigger
    ):
        _fail("G5_G4_LINEAGE_MISSING", "Linked G4 execution step result is missing or inconsistent")

    step = dict(step_result.payload)
    binding = step.get("governed_execution_binding")
    if not isinstance(binding, Mapping):
        _fail("G5_G4_LINEAGE_MISSING", "Step result lacks governed execution binding")

    task_id = _text(step.get("task_id"), "step_result.task_id")
    attempt_id = _text(step.get("attempt_id"), "step_result.attempt_id")
    root_attempt_id = _text(step.get("root_attempt_id"), "step_result.root_attempt_id")
    attempt = execution.attempt(attempt_id) if hasattr(execution, "attempt") else None
    session = composed.core_state.session(attempt.runtime_session_id) if attempt is not None else None
    if (
        attempt is None
        or attempt.mission_id != mission_id
        or attempt.task_id != task_id
        or attempt.root_attempt_id != root_attempt_id
        or session is None
        or session.mission_id != mission_id
    ):
        _fail("G5_G4_LINEAGE_MISSING", "Step execution Attempt/Session lineage is missing or cross-Mission")

    case_fact_id = _text(binding.get("case_spec_fact_id"), "governed_execution_binding.case_spec_fact_id")
    case_value_id = _text(binding.get("case_value_link_fact_id"), "governed_execution_binding.case_value_link_fact_id")
    strategy_id = _text(binding.get("strategy_version_id"), "governed_execution_binding.strategy_version_id")
    strategy_fingerprint = _text(binding.get("strategy_fingerprint"), "governed_execution_binding.strategy_fingerprint")
    batch_fact_id = _text(binding.get("binding_ref"), "governed_execution_binding.binding_ref")
    case_fact = g3.by_id(case_fact_id) if hasattr(g3, "by_id") else None
    case_value = g3.by_id(case_value_id) if hasattr(g3, "by_id") else None
    if (
        case_fact is None
        or case_fact.fact_kind != "CASE_SPECIFICATION"
        or case_fact.mission_id != mission_id
        or case_value is None
        or case_value.fact_kind != "CASE_VALUE_LINK"
        or case_value.mission_id != mission_id
        or case_fact_id not in case_value.provenance_refs
    ):
        _fail("G5_G4_LINEAGE_MISSING", "Governed Case/CaseValueLink lineage is missing")
    case = dict(case_fact.payload.get("r3_3_case") or {})
    if (
        str(case.get("tc_id") or "") != str(binding.get("case_id") or "")
        or str(case.get("case_version_id") or "") != str(binding.get("case_version_id") or "")
        or str(case.get("strategy_version_id") or "") != strategy_id
        or str(step.get("case_id") or "") != str(binding.get("case_id") or "")
        or str(step.get("case_version") or "") != str(binding.get("case_version_id") or "")
    ):
        _fail("G5_G4_ADMISSION_INVALID", "Case identity/version does not match the governed step binding")

    strategies = tuple(
        fact
        for fact in g3.by_kind("TEST_STRATEGY_PORTFOLIO")
        if str((fact.payload.get("r3_3_strategy") or {}).get("strategy_version_id") or "") == strategy_id
        and str((fact.payload.get("r3_3_strategy") or {}).get("strategy_fingerprint") or "") == strategy_fingerprint
    )
    if not strategies:
        _fail("G5_G4_LINEAGE_MISSING", "Exact governed strategy identity/fingerprint is missing")

    execution_batch = g4.by_id(batch_fact_id)
    if (
        execution_batch is None
        or execution_batch.fact_kind != "EXECUTION_BATCH"
        or execution_batch.mission_id != mission_id
        or str(execution_batch.payload.get("batch_id") or "") != str(binding.get("batch_id") or "")
        or case_fact_id not in tuple(execution_batch.payload.get("case_refs") or ())
        or str(execution_batch.payload.get("strategy_version_id") or "") != strategy_id
    ):
        _fail("G5_G4_LINEAGE_MISSING", "Exact governed execution batch is missing or inconsistent")
    goal_id = _text(execution_batch.payload.get("goal_id"), "execution_batch.goal_id")
    goal = g4.by_id(f"g4:testing-goal:{goal_id}")
    if goal is None or goal.fact_kind != "TESTING_GOAL" or goal.mission_id != mission_id:
        _fail("G5_G4_LINEAGE_MISSING", "G4 TestingGoal lineage is missing")

    cursors = tuple(
        fact
        for fact in g4.by_kind("STEP_CURSOR")
        if fact.payload.get("attempt_id") == attempt_id
        and fact.payload.get("task_id") == task_id
        and fact.payload.get("case_id") == binding.get("case_id")
        and fact.payload.get("case_version") == binding.get("case_version_id")
        and fact.payload.get("governed_execution_binding") == binding
    )
    if not cursors:
        _fail("G5_G4_LINEAGE_MISSING", "Exact governed step cursor is missing")
    step_cursor = cursors[-1]

    release_id = _text(goal.payload.get("release_id"), "testing_goal.release_id")
    quality_versions = tuple(
        value
        for value in getattr(r41, "quality_versions", ())
        if value.stream_owner_mission_id == mission_id and value.version_label == release_id
    )
    if len(quality_versions) != 1:
        _fail("G5_G4_LINEAGE_MISSING", "Exact same-Mission QualityVersion is missing or ambiguous")
    quality_version = quality_versions[0]
    campaigns = tuple(
        value
        for value in getattr(r41, "test_campaigns", ())
        if value.stream_owner_mission_id == mission_id
        and value.quality_version_ref.object_id == quality_version.quality_version_id
        and value.quality_version_ref.source_digest == quality_version.version_digest
    )
    if not campaigns:
        _fail("G5_G4_LINEAGE_MISSING", "Same-Mission campaign lineage for QualityVersion is missing")

    environment_id = _text(quality_version.environment_scope.get("environment_id"), "quality_version.environment_id")
    scope = {
        "project_id": _text(goal.payload.get("project_id"), "testing_goal.project_id"),
        "environment_id": environment_id,
        "version_scope": release_id,
    }
    expected = step.get("expected")
    actual = step.get("actual")
    evidence_ids = tuple(_text(value, "step_result.evidence_refs[]") for value in step.get("evidence_refs") or ())
    if expected is None or actual is None or not evidence_ids:
        _fail("G5_G4_LINEAGE_MISSING", "Step expected/actual/evidence lineage is incomplete")
    source_identity = _text(step.get("source_identity"), "step_result.source_identity")
    execution_node = _text(step.get("execution_node"), "step_result.execution_node")

    admission = G4ObservationAdmission(
        mission_id=mission_id,
        g4_goal_id=goal_id,
        observation_ref=_fact_ref(observation),
        step_result_ref=_fact_ref(step_result),
        oracle_result=trigger,
        scope=scope,
        quality_version_ref=_r41_ref(
            quality_version,
            ref_kind="QUALITY_VERSION",
            identity_name="quality_version_id",
            digest_name="version_digest",
        ),
        campaign_refs=tuple(
            _r41_ref(value, ref_kind="TEST_CAMPAIGN", identity_name="campaign_id", digest_name="campaign_digest")
            for value in campaigns
        ),
        case_ref=_fact_ref(case_fact),
        case_version=str(binding["case_version_id"]),
        case_value_link_ref=_fact_ref(case_value),
        strategy_refs=tuple(_fact_ref(value) for value in strategies),
        execution_batch_ref=_fact_ref(execution_batch),
        execution_attempt_ref={
            "attempt_id": attempt_id,
            "digest": canonical_sha256(attempt.to_dict()),
            "session_id": attempt.runtime_session_id,
            "root_attempt_id": root_attempt_id,
        },
        step_cursor_ref=_fact_ref(step_cursor),
        expected_ref=_derived_ref(f"{step_result.fact_id}:expected", expected, ref_kind="G4_EXPECTED"),
        actual_refs=(_derived_ref(f"{step_result.fact_id}:actual", actual, ref_kind="G4_ACTUAL"),),
        evidence_refs=tuple(
            _derived_ref(value, {"step_result_ref": step_result.fact_id, "evidence_ref": value}, ref_kind="G4_EVIDENCE")
            for value in evidence_ids
        ),
        source_identity_ref=_derived_ref(source_identity, source_identity, ref_kind="G4_SOURCE_IDENTITY"),
        execution_node_ref=_derived_ref(execution_node, execution_node, ref_kind="G4_EXECUTION_NODE"),
    )
    return AdmittedG4Observation(admission, observation, step_result, goal, execution_batch, step_cursor)
