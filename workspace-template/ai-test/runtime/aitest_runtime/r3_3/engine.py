from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r3_1.contracts import R31State
from aitest_runtime.r3_2.contracts import R32State
from aitest_runtime.r3_2.engine import r31_provenance_bundle_digest, validate_r31_reference

from .contracts import (
    BATCH_STATUSES,
    CASE_STATUSES,
    DESIGNABILITIES,
    LAYER_DECISIONS,
    LAYER_IDS,
    MAPPING_STATES,
    RECONCILIATION_SEMANTICS,
    RISK_BANDS,
    RISK_DIMENSIONS,
    R33Error,
    AutomationMapping,
    BatchDesignRequest,
    CaseBatch,
    LayerDecision,
    R32Reference,
    RiskVector,
    StandardTestCase,
    StrategyRequest,
    TestPoint,
    TestStrategy,
)


DEFAULT_RISK_WEIGHTS = {dimension: 1.0 for dimension in RISK_DIMENSIONS}
DEFAULT_RISK_THRESHOLDS = {"LOW": 25.0, "MEDIUM": 50.0, "HIGH": 75.0, "CRITICAL": 90.0}
PROFILE_DESCRIPTIONS = {
    "L1": "mapped code symbol, rule, transformation, validation or exception boundary",
    "L2": "internal component, persistence, cache, configuration, event or dependency boundary",
    "L3": "API/runtime/service/auth/idempotency/timeout/downstream/DB/MQ/transaction boundary",
    "L4": "existing code-grounded page/component/action and visible state",
    "L5": "existing durable Journey, cross-system transition or critical business journey",
    "L6": "declared performance/NFR/SLA or performance-risk boundary",
    "L7": "permission, data sensitivity, threat, authn/authz or security-risk boundary",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _values(value: Any, *names: str) -> set[str]:
    raw = _mapping(value)
    result: set[str] = set()
    for name in names:
        item = raw.get(name, ())
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, (list, tuple, set)):
            result.update(str(part) for part in item if str(part).strip())
    return result


def _text_tuple(value: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _risk_inputs_bundle(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(inputs)


def _risk_dimensions(inputs: Mapping[str, Any]) -> dict[str, int]:
    nested = inputs.get("dimensions")
    raw = _mapping(nested if isinstance(nested, Mapping) else inputs)
    values: dict[str, int] = {}
    for name in RISK_DIMENSIONS:
        value = raw.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not 0 <= int(value) <= 5:
            raise R33Error("R3_3_RISK_VECTOR_INVALID", f"risk dimension must be an integer from 0 to 5: {name}")
        values[name] = int(value)
    return values


def build_risk_vector(inputs: Mapping[str, Any], policy_version: str) -> RiskVector:
    bundle = _risk_inputs_bundle(inputs)
    dimensions = _risk_dimensions(bundle)
    weights = _mapping(bundle.get("weights")) or dict(DEFAULT_RISK_WEIGHTS)
    thresholds = _mapping(bundle.get("thresholds")) or dict(DEFAULT_RISK_THRESHOLDS)
    for band in RISK_BANDS:
        if band not in thresholds:
            raise R33Error("R3_3_RISK_VECTOR_INVALID", f"missing threshold for risk band: {band}")
    normalized_weights = {name: float(weights.get(name, 0.0)) for name in RISK_DIMENSIONS}
    if sum(normalized_weights.values()) <= 0:
        raise R33Error("R3_3_RISK_VECTOR_INVALID", "risk weights must contain a positive total")
    weighted = sum(dimensions[name] * normalized_weights[name] for name in RISK_DIMENSIONS)
    score = round(weighted / (5.0 * sum(normalized_weights.values())) * 100.0, 6)
    if score >= float(thresholds["CRITICAL"]):
        band = "CRITICAL"
    elif score >= float(thresholds["HIGH"]):
        band = "HIGH"
    elif score >= float(thresholds["MEDIUM"]):
        band = "MEDIUM"
    else:
        band = "LOW"
    evidence_refs = _text_tuple(bundle.get("evidence_refs", ()))
    return RiskVector(
        dimensions=dimensions,
        policy_version=policy_version,
        weights=normalized_weights,
        thresholds={str(key): float(value) for key, value in thresholds.items()},
        score=score,
        band=band,
        overrides=tuple(bundle.get("overrides") or ()),
        evidence_refs=evidence_refs,
    )


def _validate_r32_reference(
    state: R32State,
    request: StrategyRequest,
    *,
    r31_reference: Any,
) -> tuple[Any, Any]:
    if not isinstance(state, R32State):
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 extension state is not available")
    derivation = state.derivation(request.r3_2_reference.derivation_fingerprint)
    if derivation is None:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "referenced R3.2 derivation does not exist")
    if derivation.derivation_version_id != request.r3_2_reference.derivation_version_id:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 derivation version identity mismatch")
    if derivation.identity.mission_id != request.mission_id or derivation.identity.scope_identity != request.scope_identity:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 derivation mission/scope mismatch")
    if derivation.r3_1_reference != r31_reference:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 derivation does not reference the requested R3.1 snapshot")
    compare_digest = canonical_sha256(derivation.identity.compare_identity.to_dict())
    provider_digest = canonical_sha256(derivation.code_intelligence.to_dict())
    if compare_digest != request.r3_2_reference.compare_identity_digest:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 compare identity digest mismatch")
    if provider_digest != request.r3_2_reference.provider_envelope_digest:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 provider envelope digest mismatch")
    reconciliation = state.reconciliation(request.r3_2_reference.reconciliation_id)
    if reconciliation is None:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "referenced R3.2 reconciliation does not exist")
    if reconciliation.derivation_fingerprint != request.r3_2_reference.derivation_fingerprint:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.2 reconciliation fingerprint mismatch")
    return derivation, reconciliation


def validate_source_references(
    r31_state: R31State,
    r32_state: R32State,
    request: StrategyRequest,
) -> tuple[Any, Any, Any]:
    if not isinstance(r31_state, R31State):
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.1 extension state is not available")
    try:
        snapshot = validate_r31_reference(r31_state, request.r3_1_reference)
    except Exception as exc:
        if isinstance(exc, R33Error):
            raise
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", str(exc)) from exc
    derivation = r31_state.derivation(request.r3_1_reference.derivation_fingerprint)
    if derivation is None:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.1 derivation is not available")
    if derivation.identity.mission_id != request.mission_id or derivation.identity.scope_identity != request.scope_identity:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.1 derivation mission/scope mismatch")
    if snapshot.identity.fingerprint != request.r3_1_reference.derivation_fingerprint:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.1 fingerprint mismatch")
    if r31_provenance_bundle_digest(snapshot) != request.r3_1_reference.provenance_bundle_digest:
        raise R33Error("R3_3_SOURCE_REFERENCE_INVALID", "R3.1 provenance digest mismatch")
    r32_derivation, reconciliation = _validate_r32_reference(
        r32_state, request, r31_reference=request.r3_1_reference,
    )
    return snapshot, r32_derivation, reconciliation


def _metadata(obligation: Any) -> dict[str, Any]:
    return _mapping(getattr(obligation, "metadata", {}))


def _source_provenance_refs(obligation: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for item in getattr(obligation, "source_provenance", ()):
        refs.extend(
            (
                f"r3.1:source:{item.source_id}:{item.item_id}",
                f"source-digest:{item.source_digest}",
                f"source-bundle:{item.source_bundle_digest}",
            )
        )
    return _text_tuple(refs)


def _extract_refs(requirement: Any, change: Any, impacted_surfaces: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    req_meta = _metadata(requirement)
    change_meta = _mapping(change)
    change_present = bool(getattr(change, "change_obligation_id", None))
    code_refs = _text_tuple(
        list(_values(req_meta, "code_refs", "symbol_ids", "file_paths"))
        + list(getattr(change, "trigger_fact_refs", ()))
    )
    page_refs = _text_tuple(
        list(_values(req_meta, "page_refs", "pages", "page_ids"))
        + ([surface for surface, kind in impacted_surfaces.items() if kind == "PAGE"] if change_present else [])
    )
    api_refs = _text_tuple(
        list(_values(req_meta, "api_refs", "service_refs", "boundary_refs"))
        + ([surface for surface, kind in impacted_surfaces.items() if kind in {"API", "SERVICE", "DB", "DOWNSTREAM", "SYSTEM"}] if change_present else [])
    )
    journey_refs = _text_tuple(
        list(_values(req_meta, "journey_refs", "journeys", "critical_journey_refs"))
        + ([surface for surface, kind in impacted_surfaces.items() if kind == "JOURNEY"] if change_present else [])
    )
    target_refs = _text_tuple(list(code_refs) + list(page_refs) + list(api_refs) + list(journey_refs) + list(getattr(change, "impacted_surface_refs", ())))
    state_refs = _text_tuple(_values(req_meta, "state_transition_refs", "state_transitions"))
    return {
        "target_refs": target_refs,
        "code_refs": code_refs,
        "page_refs": page_refs,
        "api_refs": api_refs,
        "journey_refs": journey_refs,
        "state_transition_refs": state_refs,
    }


def _surface_index(derivation: Any) -> dict[str, str]:
    return {
        item.stable_surface_id: item.surface_kind
        for item in derivation.code_intelligence.impacted_surfaces
    }


def _profile_decision(
    layer_id: str,
    *,
    trigger: bool,
    trigger_refs: Iterable[str],
    required_inputs: Mapping[str, Any],
    missing_inputs: Iterable[str],
    unknown: bool,
    rationale: str,
) -> LayerDecision:
    missing = _text_tuple(missing_inputs)
    if unknown:
        decision = "UNRESOLVED"
        reason = f"{rationale}; applicability requires an unavailable governed fact"
    elif not trigger:
        decision = "NOT_SELECTED"
        reason = f"{rationale}; no governed coverage/change/risk trigger"
    elif missing:
        decision = "BLOCKED"
        reason = f"{rationale}; required design input is missing"
    else:
        decision = "SELECTED"
        reason = f"{rationale}; required design input is present"
    return LayerDecision(
        layer_id=layer_id,
        decision=decision,
        rationale=reason,
        trigger_refs=tuple(trigger_refs),
        missing_inputs=missing,
        required_inputs=required_inputs,
    )


def _layer_decisions(
    *,
    requirement: Any,
    change: Any,
    refs: Mapping[str, tuple[str, ...]],
    risk: RiskVector,
    risk_inputs: Mapping[str, Any],
    source_refs: tuple[str, ...],
    oracle_available: bool,
) -> tuple[LayerDecision, ...]:
    req_meta = _metadata(requirement)
    change_surfaces = set(refs["api_refs"])
    page_refs = refs["page_refs"]
    journey_refs = refs["journey_refs"]
    unknown_layers = set(_text_tuple(risk_inputs.get("unknown_profiles", ())))
    req_profile = "requirement:" + getattr(requirement, "obligation_id", "none")
    change_profile = getattr(change, "change_obligation_id", None)
    change_refs = (change_profile,) if change_profile else ()
    common_missing = []
    if not oracle_available:
        common_missing.append("oracle_contract")
    if not source_refs:
        common_missing.append("evidence_requirements")
    l1_trigger = bool(refs["code_refs"]) and getattr(requirement, "mapping_state", "UNMAPPED") in {"MAPPED", "PARTIAL"}
    l2_trigger = bool(_values(req_meta, "component_refs", "persistence_refs", "dependency_refs", "cache_refs", "event_refs"))
    l3_trigger = bool(change_surfaces or _values(req_meta, "auth_refs", "transaction_refs", "api_refs", "service_refs", "downstream_refs"))
    l4_trigger = bool(page_refs)
    l5_trigger = bool(journey_refs or _values(req_meta, "critical_journey_refs", "journey_refs"))
    dimensions = risk.dimensions
    perf_trigger = dimensions["performance_sensitivity"] >= 3 or bool(_values(req_meta, "performance_refs", "nfr_refs", "sla_refs"))
    security_trigger = dimensions["security_data_sensitivity"] >= 3 or bool(_values(req_meta, "security_refs", "permission_refs", "authn_refs", "authz_refs"))
    critical_journey_refs = _text_tuple(
        list(_values(risk_inputs, "critical_journey_risk_refs")) + list(_values(req_meta, "critical_journey_refs"))
    )
    l5_trigger = l5_trigger or bool(critical_journey_refs)
    perf_inputs = _mapping(risk_inputs.get("performance"))
    security_inputs = _mapping(risk_inputs.get("security"))
    return (
        _profile_decision("L1", trigger=l1_trigger, trigger_refs=tuple(refs["code_refs"]) + (req_profile,) + change_refs,
                          required_inputs={"boundary_refs": refs["code_refs"], "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + (() if refs["code_refs"] else ("code_boundary",)), unknown="L1" in unknown_layers,
                          rationale=PROFILE_DESCRIPTIONS["L1"]),
        _profile_decision("L2", trigger=l2_trigger, trigger_refs=_text_tuple(_values(req_meta, "component_refs", "persistence_refs", "dependency_refs", "cache_refs", "event_refs")) + change_refs,
                          required_inputs={"boundary_refs": _text_tuple(_values(req_meta, "component_refs", "persistence_refs", "dependency_refs", "cache_refs", "event_refs")), "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + (() if l2_trigger else ()), unknown="L2" in unknown_layers,
                          rationale=PROFILE_DESCRIPTIONS["L2"]),
        _profile_decision("L3", trigger=l3_trigger, trigger_refs=tuple(refs["api_refs"]) + change_refs,
                          required_inputs={"boundary_refs": refs["api_refs"], "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + (() if refs["api_refs"] else ("runtime_boundary",)), unknown="L3" in unknown_layers,
                          rationale=PROFILE_DESCRIPTIONS["L3"]),
        _profile_decision("L4", trigger=l4_trigger, trigger_refs=page_refs,
                          required_inputs={"page_refs": page_refs, "visible_oracle": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + (() if page_refs else ("page_binding",)), unknown="L4" in unknown_layers,
                          rationale=PROFILE_DESCRIPTIONS["L4"]),
        _profile_decision("L5", trigger=l5_trigger, trigger_refs=journey_refs + critical_journey_refs,
                          required_inputs={"journey_refs": journey_refs, "actor": _text_tuple(_values(req_meta, "actors", "actor_refs")), "start_end_state": _text_tuple(_values(req_meta, "start_state_refs", "end_state_refs")), "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + (() if journey_refs else ("journey_ref",)) + (() if _values(req_meta, "actors", "actor_refs") else ("actor",)) + (() if _values(req_meta, "start_state_refs", "end_state_refs") else ("start_end_state",)),
                          unknown="L5" in unknown_layers, rationale=PROFILE_DESCRIPTIONS["L5"]),
        _profile_decision("L6", trigger=perf_trigger, trigger_refs=_text_tuple(_values(req_meta, "performance_refs", "nfr_refs", "sla_refs")) + (f"risk:performance_sensitivity={dimensions['performance_sensitivity']}",),
                          required_inputs={"performance": perf_inputs, "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + tuple(name for name in ("workload", "metrics", "thresholds") if name not in perf_inputs),
                          unknown="L6" in unknown_layers, rationale=PROFILE_DESCRIPTIONS["L6"]),
        _profile_decision("L7", trigger=security_trigger, trigger_refs=_text_tuple(_values(req_meta, "security_refs", "permission_refs", "authn_refs", "authz_refs")) + (f"risk:security_data_sensitivity={dimensions['security_data_sensitivity']}",),
                          required_inputs={"security": security_inputs, "oracle_contract": oracle_available, "evidence_refs": source_refs},
                          missing_inputs=tuple(common_missing) + tuple(name for name in ("security_property", "actor", "expected_behavior") if name not in security_inputs),
                          unknown="L7" in unknown_layers, rationale=PROFILE_DESCRIPTIONS["L7"]),
    )


def _oracle_for(requirement: Any, change: Any, refs: Mapping[str, tuple[str, ...]], source_refs: tuple[str, ...], point_id: str) -> tuple[dict[str, Any], str | None]:
    req_meta = _metadata(requirement)
    if req_meta.get("oracle_missing") is True:
        return {}, None
    supplied = req_meta.get("oracle_contract")
    if isinstance(supplied, Mapping):
        oracle = dict(supplied)
    else:
        behavior = getattr(requirement, "text", None) or getattr(change, "affected_behavior", None) or "governed behavior"
        oracle = {
            "business_property": behavior,
            "observation_fields": list(refs["target_refs"]) or ["governed_observation"],
            "pass_condition": "observed outcome satisfies the source-grounded behavior contract",
            "fail_condition": "observed outcome violates the source-grounded behavior contract",
            "insufficient_evidence_condition": "required evidence is unavailable or contradictory",
        }
    required = ("business_property", "observation_fields", "pass_condition", "fail_condition", "insufficient_evidence_condition")
    if not all(oracle.get(name) for name in required):
        return {}, None
    return oracle, canonical_sha256(oracle)


def _point_from_item(
    *,
    strategy_fingerprint: str,
    strategy_version_id: str,
    item: Any,
    requirement: Any | None,
    change: Any | None,
    derivation: Any,
    risk: RiskVector,
    risk_inputs: Mapping[str, Any],
    point_order: int,
) -> TestPoint:
    requirement = requirement
    change = change
    impacted_surfaces = _surface_index(derivation)
    refs = _extract_refs(requirement, change, impacted_surfaces) if requirement is not None and change is not None else {
        name: () for name in ("target_refs", "code_refs", "page_refs", "api_refs", "journey_refs", "state_transition_refs")
    }
    if requirement is None:
        refs = {
            "target_refs": _text_tuple(getattr(change, "impacted_surface_refs", ())),
            "code_refs": _text_tuple(getattr(change, "trigger_fact_refs", ())),
            "page_refs": (), "api_refs": _text_tuple(getattr(change, "impacted_surface_refs", ())),
            "journey_refs": (), "state_transition_refs": (),
        }
    if change is None and requirement is not None:
        refs = _extract_refs(requirement, {}, impacted_surfaces)
    req_id = getattr(requirement, "obligation_id", None)
    change_id = getattr(change, "change_obligation_id", None)
    source_refs = _text_tuple(
        _source_provenance_refs(requirement) if requirement is not None else ()
    )
    if change is not None:
        source_refs = _text_tuple(source_refs + tuple(getattr(change, "provenance_refs", ())))
    relation_semantics = tuple(getattr(item, "gap_kinds", ())) + (getattr(item, "semantic", "UNMAPPED"),)
    relation_semantics = _text_tuple(relation_semantics)
    source_members = []
    if requirement is not None:
        source_members.append({
            "source_kind": "REQUIREMENT", "source_id": req_id,
            "source_version": getattr(requirement.source_provenance[0], "revision", "unknown"),
            "relation_semantic": getattr(item, "semantic", "REQUIREMENT_ONLY"),
        })
    if change is not None:
        source_members.append({
            "source_kind": "CHANGE", "source_id": change_id,
            "source_version": getattr(derivation, "derivation_fingerprint", "unknown"),
            "relation_semantic": getattr(item, "semantic", "CHANGE_ONLY"),
        })
    if not source_members:
        source_members.append({"source_kind": "RISK", "source_id": f"risk:{point_order}", "source_version": risk.policy_version, "relation_semantic": "UNMAPPED"})
    source_members.append({"source_kind": "RISK", "source_id": f"risk:{risk.policy_version}:{point_order}", "source_version": risk.policy_version, "relation_semantic": "RISK"})
    oracle, oracle_digest = _oracle_for(requirement, change, refs, source_refs, f"r3.3:point:{point_order}")
    decisions = _layer_decisions(
        requirement=requirement or type("ChangeOnly", (), {"obligation_id": "", "mapping_state": "UNMAPPED", "metadata": {}})(),
        change=change,
        refs=refs, risk=risk, risk_inputs=risk_inputs, source_refs=source_refs,
        oracle_available=bool(oracle_digest),
    )
    selected = [item for item in decisions if item.decision == "SELECTED"]
    blocked = [item for item in decisions if item.decision in {"BLOCKED", "UNRESOLVED"}]
    if not oracle_digest or not source_refs:
        designability = "BLOCKED"
    elif not selected:
        designability = "UNMAPPED" if "UNMAPPED" in relation_semantics else ("BLOCKED" if blocked else "PARTIAL")
    else:
        designability = "DESIGNABLE"
    point_seed = {
        "strategy_fingerprint": strategy_fingerprint, "requirement_id": req_id,
        "change_id": change_id, "semantic": list(relation_semantics), "order": point_order,
    }
    point_id = f"r3.3:point:{canonical_sha256(point_seed)}"
    oracle_ref = f"r3.3:oracle:{point_id}" if oracle_digest else None
    gaps = list(relation_semantics)
    if designability == "BLOCKED" and not oracle_digest:
        gaps.append("MISSING_ORACLE_OR_EVIDENCE")
    if blocked:
        gaps.extend(f"{decision.layer_id}:{missing}" for decision in blocked for missing in decision.missing_inputs)
    return TestPoint(
        point_id=point_id, strategy_version_id=strategy_version_id, source_members=tuple(source_members),
        coverage_obligation_refs=(req_id,) if req_id else (), change_impact_obligation_refs=(change_id,) if change_id else (),
        target_refs=refs["target_refs"], code_refs=refs["code_refs"], page_refs=refs["page_refs"],
        api_refs=refs["api_refs"], journey_refs=refs["journey_refs"], behavior_contract={
            "requirement_text": getattr(requirement, "text", None),
            "change_behavior": getattr(change, "affected_behavior", None),
            "reconciliation_semantics": list(relation_semantics),
        },
        state_transition_refs=refs["state_transition_refs"], risk_vector=risk, risk_band=risk.band,
        risk_evidence_refs=risk.evidence_refs, layer_decisions=tuple(decisions), oracle_contract_ref=oracle_ref,
        oracle_design_digest=oracle_digest, evidence_requirement_refs=source_refs,
        designability=designability, batch_id=f"r3.3:batch:unassigned:{canonical_sha256(point_seed)}",
        deterministic_order=point_order, gaps=_text_tuple(gaps), source_provenance=source_refs,
        metadata={"oracle_contract": oracle, "requirement_metadata": _metadata(requirement) if requirement is not None else {}},
    )


def build_strategy(
    request: StrategyRequest,
    r31_state: R31State,
    r32_state: R32State,
) -> tuple[TestStrategy, tuple[TestPoint, ...]]:
    snapshot, derivation, reconciliation = validate_source_references(r31_state, r32_state, request)
    risk = build_risk_vector(request.risk_inputs, request.risk_policy_version)
    strategy_identity = {
        "mission_id": request.mission_id, "scope_identity": request.scope_identity,
        "r3_1_reference": request.r3_1_reference.to_dict(),
        "r3_2_reference": request.r3_2_reference.to_dict(),
        "risk_inputs": request.risk_inputs, "risk_policy_version": request.risk_policy_version,
        "layer_taxonomy_version": request.layer_taxonomy_version,
        "case_design_policy_version": request.case_design_policy_version,
        "batching_policy_version": request.batching_policy_version,
        "context_refs": {
            key: request.risk_inputs.get(key)
            for key in ("critical_journey_risk_refs", "historical_risk_refs", "page_topology_data_permission_nfr_refs", "knowledge_refs")
            if key in request.risk_inputs
        },
        "automation_inventory_digest": canonical_sha256(request.automation_inventory_ref) if request.automation_inventory_ref is not None else None,
    }
    fingerprint = canonical_sha256(strategy_identity)
    strategy_id = f"r3.3:strategy:{fingerprint}"
    requirements = {item.obligation_id: item for item in snapshot.obligations}
    changes = {item.change_obligation_id: item for item in derivation.change_obligations}
    points = []
    for index, item in enumerate(reconciliation.items):
        points.append(
            _point_from_item(
                strategy_fingerprint=fingerprint, strategy_version_id=strategy_id, item=item,
                requirement=requirements.get(item.requirement_obligation_id) if item.requirement_obligation_id else None,
                change=changes.get(item.change_obligation_id) if item.change_obligation_id else None,
                derivation=derivation, risk=risk, risk_inputs=request.risk_inputs, point_order=index,
            )
        )
    selected_counts = {layer: sum(1 for point in points for decision in point.layer_decisions if decision.layer_id == layer and decision.decision == "SELECTED") for layer in LAYER_IDS}
    decision_counts = {decision: sum(1 for point in points for item in point.layer_decisions if item.decision == decision) for decision in LAYER_DECISIONS}
    profile_digest = canonical_sha256(PROFILE_DESCRIPTIONS)
    risk_policy_digest = canonical_sha256({"version": request.risk_policy_version, "weights": risk.weights, "thresholds": risk.thresholds})
    source_provenance = _text_tuple(
        [f"r3.1:derivation:{request.r3_1_reference.derivation_version_id}", f"r3.1:snapshot:{request.r3_1_reference.snapshot_id}",
         f"r3.2:derivation:{request.r3_2_reference.derivation_version_id}", f"r3.2:reconciliation:{request.r3_2_reference.reconciliation_id}"]
        + list(risk.evidence_refs)
    )
    strategy = TestStrategy(
        strategy_id=strategy_id, strategy_version_id=strategy_id, mission_id=request.mission_id,
        scope_identity=request.scope_identity, r3_1_reference=request.r3_1_reference, r3_2_reference=request.r3_2_reference,
        risk_bundle_reference=request.risk_inputs, risk_policy_version=request.risk_policy_version,
        risk_policy_digest=risk_policy_digest, layer_taxonomy_version=request.layer_taxonomy_version,
        profile_catalog_digest=profile_digest, case_design_policy_version=request.case_design_policy_version,
        batching_policy_version=request.batching_policy_version,
        source_member_counts={
            "requirement_coverage_obligation_count": len(snapshot.obligations),
            "change_impact_obligation_count": len(derivation.change_obligations),
            "reconciliation_item_count": len(reconciliation.items),
        },
        selected_profile_counts=selected_counts, decision_counts=decision_counts,
        coverage_obligation_count=len(snapshot.obligations), change_impact_obligation_count=len(derivation.change_obligations),
        test_point_count=len(points), standard_case_count=0, automation_mapping_count=0,
        automation_method_count=_automation_method_count(request.automation_inventory_ref),
        strategy_status="DRAFT", strategy_fingerprint=fingerprint, idempotency_key=request.idempotency_key,
        requested_by=request.requested_by, correlation_id=request.correlation_id,
        source_provenance=source_provenance,
        evidence_refs=_text_tuple(
            list(derivation.evidence_references) + list(getattr(reconciliation, "provenance_refs", ()))
            + [f"r3.1-provenance:{request.r3_1_reference.provenance_bundle_digest}",
               f"r3.2-provider-envelope:{request.r3_2_reference.provider_envelope_digest}"]
        ),
        automation_inventory_ref=request.automation_inventory_ref,
    )
    return strategy, tuple(points)


def _automation_method_count(inventory: Mapping[str, Any] | None) -> int:
    if not isinstance(inventory, Mapping):
        return 0
    methods = inventory.get("methods") or inventory.get("automation_methods") or ()
    ids = []
    for item in methods if isinstance(methods, (list, tuple)) else ():
        if isinstance(item, Mapping):
            value = item.get("method_id") or item.get("automation_method_ref") or item.get("id")
            if value:
                ids.append(str(value))
        elif str(item).strip():
            ids.append(str(item))
    return len(set(ids))


def _case_status(point: TestPoint) -> str:
    blocked = any(decision.decision in {"BLOCKED", "UNRESOLVED"} for decision in point.layer_decisions)
    return "DRAFT_WITH_GAPS" if blocked or point.designability != "DESIGNABLE" else "DRAFT"


def _case_for_point(point: TestPoint, layer: LayerDecision, strategy: TestStrategy, batch_id: str) -> StandardTestCase:
    metadata = _mapping(point.metadata)
    oracle = _mapping(metadata.get("oracle_contract"))
    if not oracle:
        raise R33Error("R3_3_MISSING_ORACLE_OR_EVIDENCE", f"point has no designable oracle: {point.point_id}")
    case_seed = {"strategy": strategy.strategy_fingerprint, "point": point.point_id, "layer": layer.layer_id}
    case_version_id = f"r3.3:case:{canonical_sha256(case_seed)}:v1"
    requirement_id = point.coverage_obligation_refs[0] if point.coverage_obligation_refs else None
    requirement_meta = _mapping(metadata.get("requirement_metadata"))
    title = f"{layer.layer_id} standard design for {requirement_id or point.point_id}"
    evidence_requirements = tuple({"evidence_id": ref, "required": True, "source": "R3.1/R3.2"} for ref in point.evidence_requirement_refs)
    return StandardTestCase(
        tc_id=case_version_id.split(":v1")[0], case_version_id=case_version_id, version=1,
        lifecycle_status=_case_status(point), strategy_version_id=strategy.strategy_version_id,
        test_point_id=point.point_id, batch_id=batch_id,
        coverage_obligation_refs=point.coverage_obligation_refs, requirement_id=requirement_id,
        sst_id=requirement_meta.get("sst_id"), design_refs=_text_tuple(requirement_meta.get("design_refs", ())),
        code_refs=point.code_refs, change_impact_refs=point.change_impact_obligation_refs,
        reconciliation_semantics=_text_tuple(item for item in point.gaps if item in RECONCILIATION_SEMANTICS), risk_refs=point.risk_evidence_refs,
        layer_id=layer.layer_id, layer_profile_version=layer.profile_version,
        case_type=layer.layer_id, priority="CRITICAL" if point.risk_band == "CRITICAL" else "STANDARD",
        risk=point.risk_vector, source_context={
            "r3_1_reference": strategy.r3_1_reference.to_dict(),
            "r3_2_reference": strategy.r3_2_reference.to_dict(),
            "relation_semantics": list(point.gaps),
            "layer_decision": layer.to_dict(),
        },
        objective=point.behavior_contract.get("requirement_text") or point.behavior_contract.get("change_behavior") or "governed behavior",
        title=title, preconditions=tuple({"precondition": item} for item in _text_tuple(requirement_meta.get("preconditions", ()))),
        test_data=tuple({"data_ref": item} for item in _text_tuple(requirement_meta.get("test_data", ()))),
        environment_and_boundary={
            "target_refs": list(point.target_refs), "code_refs": list(point.code_refs),
            "page_refs": list(point.page_refs), "api_refs": list(point.api_refs), "journey_refs": list(point.journey_refs),
        },
        steps=({"step": 1, "action": f"exercise {layer.layer_id} governed boundary", "boundary_refs": list(layer.required_inputs.get("boundary_refs", ()))},),
        expected_results=({"observation": oracle["observation_fields"], "pass_condition": oracle["pass_condition"]},),
        postconditions=({"condition": "retain source-grounded evidence and state observation"},),
        oracle_contract=oracle,
        evidence_requirements=evidence_requirements,
        execution_profile={"declarative_only": True, "layer_id": layer.layer_id, "session_owner": "R2.5"},
        automation_mapping_refs=(),
        specification_status=_case_status(point),
        source_provenance=point.source_provenance, evidence_refs=point.evidence_requirement_refs,
    )


def _matching_inventory_assets(inventory: Mapping[str, Any] | None, cases: tuple[StandardTestCase, ...]) -> tuple[AutomationMapping, ...]:
    if not isinstance(inventory, Mapping):
        return ()
    assets = inventory.get("assets") or inventory.get("automation_assets") or ()
    if not isinstance(assets, (list, tuple)):
        return ()
    cases_by_id = {case.case_version_id: case for case in cases}
    cases_by_point = {case.test_point_id: case for case in cases}
    mappings: list[AutomationMapping] = []
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        case_refs = list(asset.get("case_version_refs") or ())
        if asset.get("case_version_id"):
            case_refs.append(asset["case_version_id"])
        if asset.get("test_point_id") and asset["test_point_id"] in cases_by_point:
            case_refs.append(cases_by_point[asset["test_point_id"]].case_version_id)
        coverage_id = asset.get("coverage_obligation_id")
        if coverage_id:
            case_refs.extend(
                case.case_version_id
                for case in cases
                if str(coverage_id) in case.coverage_obligation_refs
            )
        method_refs = asset.get("automation_method_refs") or asset.get("method_refs") or asset.get("method_id")
        if isinstance(method_refs, str):
            method_refs = (method_refs,)
        if not method_refs:
            continue
        for case_ref in _text_tuple(case_refs):
            case = cases_by_id.get(case_ref)
            if case is None:
                continue
            mapping_seed = {"case": case.case_version_id, "asset": asset.get("asset_id") or asset.get("id") or case.case_version_id, "methods": list(method_refs)}
            mappings.append(
                AutomationMapping(
                    mapping_id=f"r3.3:mapping:{canonical_sha256(mapping_seed)}",
                    case_version_id=case.case_version_id,
                    automation_asset_ref=str(asset.get("asset_id") or asset.get("id") or "automation-asset"),
                    automation_method_refs=tuple(str(item) for item in method_refs),
                    implementation_type=str(asset.get("implementation_type") or "existing-automation"),
                    adapter_ref=asset.get("adapter_ref"), provider_ref=asset.get("provider_ref"),
                    mapping_relation=str(asset.get("mapping_relation") or "IMPLEMENTS"),
                    mapping_state="EVIDENCE_BACKED" if asset.get("evidence_refs") else "PROPOSED",
                    source_refs=tuple(case.source_provenance), evidence_refs=tuple(asset.get("evidence_refs") or ()),
                    mapping_policy_version=str(asset.get("mapping_policy_version") or "r3.3.mapping.v1"),
                )
            )
    unique: dict[str, AutomationMapping] = {item.mapping_id: item for item in mappings}
    return tuple(unique[key] for key in sorted(unique))


def design_case_batch(
    strategy: TestStrategy,
    points: tuple[TestPoint, ...],
    request: BatchDesignRequest,
    *,
    existing_cases: tuple[StandardTestCase, ...] = (),
) -> tuple[CaseBatch, tuple[StandardTestCase, ...], tuple[AutomationMapping, ...], TestStrategy]:
    if request.expected_strategy_fingerprint != strategy.strategy_fingerprint:
        raise R33Error("R3_3_STRATEGY_FINGERPRINT_MISMATCH", "batch request strategy fingerprint mismatch")
    ordered = tuple(sorted(points, key=lambda item: item.deterministic_order))
    start = 0
    if request.batch_cursor:
        matches = [index for index, point in enumerate(ordered) if point.point_id == request.batch_cursor]
        if not matches:
            raise R33Error("R3_3_BATCH_CURSOR_INVALID", "batch cursor does not reference a TestPoint")
        start = matches[0] + 1
    if start >= len(ordered):
        raise R33Error("R3_3_BATCH_CURSOR_EXHAUSTED", "batch cursor has no remaining TestPoints")
    selected_points = ordered[start:start + request.batch_limit]
    group_seed = {
        "behavior_boundaries": [point.behavior_contract for point in selected_points],
        "state_transitions": [point.state_transition_refs for point in selected_points],
        "layers": [[item.layer_id for item in point.layer_decisions if item.decision == "SELECTED"] for point in selected_points],
        "risk_bands": [point.risk_band for point in selected_points],
        "oracle_shapes": [point.oracle_design_digest for point in selected_points],
        "environment_boundaries": [point.target_refs for point in selected_points],
        "evidence_profiles": [point.evidence_requirement_refs for point in selected_points],
    }
    group_key = canonical_sha256(group_seed)
    batch_order = start // request.batch_limit
    computed_batch_id = f"r3.3:batch:{canonical_sha256({'strategy_fingerprint': strategy.strategy_fingerprint, 'canonical_group_key': group_key, 'batch_ordinal': batch_order})}"
    if request.batch_id is not None and request.batch_id != computed_batch_id:
        raise R33Error("R3_3_BATCH_ID_MISMATCH", "batch_id does not match deterministic batch identity")
    batch_id = request.batch_id or computed_batch_id
    cases: list[StandardTestCase] = []
    blocked_refs: list[str] = []
    for point in selected_points:
        if point.designability != "DESIGNABLE":
            blocked_refs.append(point.point_id)
            continue
        for layer in point.layer_decisions:
            if layer.decision == "SELECTED":
                cases.append(_case_for_point(point, layer, strategy, batch_id))
    case_tuple = tuple(cases)
    mappings = _matching_inventory_assets(strategy.automation_inventory_ref, case_tuple)
    next_cursor = selected_points[-1].point_id
    finished = start + len(selected_points) >= len(ordered)
    batch_status = "BLOCKED" if not case_tuple and blocked_refs else ("COMPLETED" if finished else "IN_PROGRESS")
    batch = CaseBatch(
        batch_id=batch_id, strategy_version_id=strategy.strategy_version_id, batch_order=batch_order,
        batch_cursor=request.batch_cursor or "", batch_limit=request.batch_limit, batch_status=batch_status,
        designer_session_ref=request.designer_session_ref,
        test_point_refs=tuple(point.point_id for point in selected_points),
        standard_case_version_refs=tuple(case.case_version_id for case in case_tuple),
        automation_mapping_refs=tuple(item.mapping_id for item in mappings),
        blocked_point_refs=tuple(blocked_refs), next_cursor=None if finished else next_cursor,
        group_key=group_key, source_evidence_refs=_text_tuple(
            ref for point in selected_points for ref in point.evidence_requirement_refs
        ),
    )
    prior_case_ids = {item.case_version_id for item in existing_cases}
    new_case_count = sum(1 for item in case_tuple if item.case_version_id not in prior_case_ids)
    prior_mapping_ids = set()
    strategy_updated = replace(
        strategy,
        standard_case_count=strategy.standard_case_count + new_case_count,
        automation_mapping_count=strategy.automation_mapping_count + len(mappings),
        automation_method_count=len({
            method for mapping in mappings for method in mapping.automation_method_refs
        } | set(),
        ),
        strategy_status="DESIGNED",
    )
    return batch, case_tuple, mappings, strategy_updated
