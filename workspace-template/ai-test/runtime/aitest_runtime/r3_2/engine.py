from __future__ import annotations

from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r3_1.contracts import R31State, TestCoverageObligation

from .contracts import (
    ChangeImpactDerivation,
    ChangeImpactIdentity,
    ChangeImpactObligation,
    ChangeImpactRequest,
    CodeIntelligenceEnvelope,
    ImpactEdge,
    ImpactedSurface,
    R31Reference,
    R32Error,
    ReconciliationItem,
    ReconciliationSnapshot,
)


def r31_provenance_bundle_digest(snapshot: Any) -> str:
    """Compute the read-only provenance digest expected by an R3.2 reference."""
    obligations = getattr(snapshot, "obligations", ())
    payload = []
    for obligation in sorted(obligations, key=lambda item: item.obligation_id):
        payload.append({
            "obligation_id": obligation.obligation_id,
            "source_provenance": [item.to_dict() for item in obligation.source_provenance],
        })
    return canonical_sha256(payload)


def validate_r31_reference(state: R31State, reference: R31Reference) -> Any:
    if not isinstance(state, R31State):
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 extension state is not available")
    snapshot = state.snapshot(reference.snapshot_id)
    if snapshot is None:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "referenced R3.1 snapshot does not exist")
    derivation = state.derivation(reference.derivation_fingerprint)
    if derivation is None:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "referenced R3.1 derivation does not exist")
    if derivation.derivation_version_id != reference.derivation_version_id:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 derivation version identity mismatch")
    if snapshot.derivation_version_id != reference.derivation_version_id:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 snapshot derivation identity mismatch")
    if snapshot.identity.fingerprint != reference.derivation_fingerprint:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 derivation fingerprint mismatch")
    if snapshot.identity.source_bundle_digest != reference.source_bundle_digest:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 source bundle digest mismatch")
    if r31_provenance_bundle_digest(snapshot) != reference.provenance_bundle_digest:
        raise R32Error("R3_2_R31_REFERENCE_INVALID", "R3.1 provenance bundle digest mismatch")
    return snapshot


def _metadata_values(value: Any, names: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    metadata = value if isinstance(value, Mapping) else {}
    for name in names:
        raw = metadata.get(name, ())
        if isinstance(raw, str):
            result.add(raw)
        elif isinstance(raw, (list, tuple, set)):
            result.update(str(item) for item in raw if str(item).strip())
    return result


def _requirement_keys(obligation: TestCoverageObligation) -> set[str]:
    keys = {obligation.obligation_id}
    names = ("code_refs", "symbol_ids", "surface_ids", "file_paths", "correlation_keys")
    keys.update(_metadata_values(obligation.metadata, names))
    for provenance in obligation.source_provenance:
        keys.update(_metadata_values(provenance.metadata, names))
    return {item for item in keys if item.strip()}


def _surface_refs_for(symbol: str, file_path: str, surfaces: Iterable[ImpactedSurface]) -> tuple[ImpactedSurface, ...]:
    result = []
    for surface in surfaces:
        if any(ref in {f"symbol:{symbol}", f"file:{file_path}"} for ref in surface.evidence_refs):
            result.append(surface)
    return tuple(result)


def _edges_for(symbol: str, edges: Iterable[ImpactEdge]) -> tuple[ImpactEdge, ...]:
    return tuple(edge for edge in edges if edge.from_node == symbol)


def _obligation_resolution(edges: tuple[ImpactEdge, ...], surfaces: tuple[ImpactedSurface, ...]) -> str:
    resolved_edges = [edge for edge in edges if not edge.to_node.startswith("unresolved::") and edge.confidence >= 0.75]
    partial_edges = [edge for edge in edges if edge.to_node.startswith("unresolved::") or edge.confidence < 0.75]
    resolved_surfaces = [surface for surface in surfaces if surface.confidence >= 0.75]
    if resolved_edges or resolved_surfaces:
        return "RESOLVED"
    if partial_edges or surfaces:
        return "PARTIAL"
    return "UNMAPPED"


def derive_change_obligations(envelope: CodeIntelligenceEnvelope) -> tuple[ChangeImpactObligation, ...]:
    obligations: list[ChangeImpactObligation] = []
    files_by_path = {item.file_path: item for item in envelope.changed_files}
    symbols_by_file: dict[str, list[Any]] = {}
    for symbol in envelope.changed_symbols:
        symbols_by_file.setdefault(symbol.file_path, []).append(symbol)
    provenance = envelope.source_refs
    for symbol in sorted(envelope.changed_symbols, key=lambda item: item.symbol_id):
        file_fact = files_by_path.get(symbol.file_path)
        edges = _edges_for(symbol.symbol_id, envelope.impact_edges)
        surfaces = _surface_refs_for(symbol.symbol_id, symbol.file_path, envelope.impacted_surfaces)
        trigger_refs = (f"symbol:{symbol.symbol_id}", f"file:{symbol.file_path}")
        surface_refs = tuple(item.stable_surface_id for item in surfaces)
        keys = (symbol.symbol_id, symbol.file_path, *surface_refs)
        behavior = symbol.new_signature or symbol.old_signature or symbol.symbol_id
        evidence = tuple(dict.fromkeys(provenance + symbol.source_provenance + (f"symbol:{symbol.symbol_id}",)))
        resolution = _obligation_resolution(edges, surfaces)
        identity = {
            "compare_identity": envelope.compare_identity.to_dict(),
            "trigger_fact_refs": list(trigger_refs),
            "impacted_surface_refs": list(surface_refs),
            "affected_behavior": behavior,
            "risk_hint": "changed-symbol",
            "impact_resolution": resolution,
            "correlation_keys": list(keys),
            "provenance_refs": list(evidence),
        }
        fingerprint = canonical_sha256(identity)
        obligations.append(
            ChangeImpactObligation(
                change_obligation_id=f"r3.2:change:{fingerprint}", compare_identity=envelope.compare_identity,
                trigger_fact_refs=trigger_refs, impacted_surface_refs=surface_refs, affected_behavior=behavior,
                risk_hint="changed-symbol" if file_fact else "symbol-without-file-fact", impact_resolution=resolution,
                correlation_keys=keys, provenance_refs=evidence, obligation_fingerprint=fingerprint,
            )
        )
    for file_fact in sorted(envelope.changed_files, key=lambda item: item.file_path):
        if symbols_by_file.get(file_fact.file_path):
            continue
        trigger_refs = (f"file:{file_fact.file_path}",)
        evidence = tuple(dict.fromkeys(provenance + file_fact.source_provenance + (f"file:{file_fact.file_path}",)))
        identity = {
            "compare_identity": envelope.compare_identity.to_dict(),
            "trigger_fact_refs": list(trigger_refs), "impacted_surface_refs": [],
            "affected_behavior": f"Changed file {file_fact.file_path}; symbol/call-chain impact unresolved",
            "risk_hint": "changed-file-without-symbol-resolution", "impact_resolution": "UNMAPPED",
            "correlation_keys": [file_fact.file_path], "provenance_refs": list(evidence),
        }
        fingerprint = canonical_sha256(identity)
        obligations.append(
            ChangeImpactObligation(
                change_obligation_id=f"r3.2:change:{fingerprint}", compare_identity=envelope.compare_identity,
                trigger_fact_refs=trigger_refs, impacted_surface_refs=(), affected_behavior=identity["affected_behavior"],
                risk_hint=identity["risk_hint"], impact_resolution="UNMAPPED", correlation_keys=(file_fact.file_path,),
                provenance_refs=evidence, obligation_fingerprint=fingerprint,
            )
        )
    return tuple(obligations)


def _requirement_provenance(obligation: TestCoverageObligation) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        (f"r3.1:obligation:{obligation.obligation_id}",)
        + tuple(f"r3.1:source:{item.source_id}:{item.item_id}" for item in obligation.source_provenance)
    ))


def _item_id(semantic: str, requirement_id: str | None, change_id: str | None, gaps: tuple[str, ...]) -> str:
    identity = {
        "semantic": semantic,
        "requirement_obligation_id": requirement_id,
        "change_obligation_id": change_id,
        "gap_kinds": list(gaps),
    }
    return f"r3.2:reconciliation-item:{canonical_sha256(identity)}"


def reconcile(
    snapshot: Any,
    reference: R31Reference,
    change_obligations: tuple[ChangeImpactObligation, ...],
    derivation_fingerprint: str,
) -> ReconciliationSnapshot:
    requirements = tuple(snapshot.obligations)
    changes = tuple(change_obligations)
    requirement_keys = {item.obligation_id: _requirement_keys(item) for item in requirements}
    change_keys = {item.change_obligation_id: set(item.correlation_keys) for item in changes}
    used_changes: set[str] = set()
    items: list[ReconciliationItem] = []
    for requirement in sorted(requirements, key=lambda item: item.obligation_id):
        matches = [
            change for change in changes
            if change.change_obligation_id not in used_changes and requirement_keys[requirement.obligation_id].intersection(change_keys[change.change_obligation_id])
        ]
        gap_kinds = tuple(sorted({gap.kind for gap in requirement.coverage_gaps if gap.kind == "REQUIREMENT_CODE_GAP"}))
        if matches:
            change = matches[0]
            used_changes.add(change.change_obligation_id)
            evidence = tuple(sorted(requirement_keys[requirement.obligation_id].intersection(change_keys[change.change_obligation_id])))
            items.append(
                ReconciliationItem(
                    reconciliation_item_id=_item_id("OVERLAP", requirement.obligation_id, change.change_obligation_id, gap_kinds),
                    semantic="OVERLAP", requirement_obligation_id=requirement.obligation_id,
                    change_obligation_id=change.change_obligation_id, gap_kinds=gap_kinds,
                    correlation_evidence=evidence, provenance_refs=_requirement_provenance(requirement) + change.provenance_refs,
                )
            )
        else:
            semantic = "REQUIREMENT_CODE_GAP" if "REQUIREMENT_CODE_GAP" in gap_kinds else "REQUIREMENT_ONLY"
            items.append(
                ReconciliationItem(
                    reconciliation_item_id=_item_id(semantic, requirement.obligation_id, None, gap_kinds), semantic=semantic,
                    requirement_obligation_id=requirement.obligation_id, change_obligation_id=None, gap_kinds=gap_kinds,
                    correlation_evidence=(), provenance_refs=_requirement_provenance(requirement),
                )
            )
    for change in sorted(changes, key=lambda item: item.change_obligation_id):
        if change.change_obligation_id in used_changes:
            continue
        gaps = ("UNMAPPED",) if change.impact_resolution == "UNMAPPED" else ()
        items.append(
            ReconciliationItem(
                reconciliation_item_id=_item_id("CHANGE_ONLY", None, change.change_obligation_id, gaps), semantic="CHANGE_ONLY",
                requirement_obligation_id=None, change_obligation_id=change.change_obligation_id, gap_kinds=gaps,
                correlation_evidence=(), provenance_refs=change.provenance_refs,
            )
        )
    counts_by_semantic: dict[str, int] = {}
    for item in items:
        counts_by_semantic[item.semantic] = counts_by_semantic.get(item.semantic, 0) + 1
        for gap in item.gap_kinds:
            counts_by_semantic[gap] = counts_by_semantic.get(gap, 0) + 1
    counts_by_source = {
        "requirement_coverage_obligation_count": len(requirements),
        "change_impact_obligation_count": len(changes),
        "reconciliation_item_count": len(items),
    }
    reconciliation_id = f"r3.2:reconciliation:{derivation_fingerprint}"
    return ReconciliationSnapshot(
        reconciliation_id=reconciliation_id, derivation_fingerprint=derivation_fingerprint,
        r3_1_reference=reference, items=tuple(items), counts_by_source=counts_by_source,
        counts_by_semantic=counts_by_semantic,
    )


def build_derivation(
    request: ChangeImpactRequest,
    r31_state: R31State,
    envelope: CodeIntelligenceEnvelope,
) -> tuple[ChangeImpactDerivation, ReconciliationSnapshot]:
    snapshot = validate_r31_reference(r31_state, request.r3_1_reference)
    if envelope.compare_identity.policy_version != request.policy_version:
        raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "provider policy_version does not match request")
    if envelope.compare_identity.untracked_policy != request.repository.untracked_policy:
        raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "provider untracked_policy does not match request")
    identity = ChangeImpactIdentity(
        mission_id=request.mission_id, scope_identity=request.scope_identity,
        compare_identity=envelope.compare_identity, provider_id=envelope.provider_id,
        provider_version=envelope.provider_version, provider_input_digest=envelope.provider_input_digest,
        code_graph_digest=envelope.code_graph_digest, r3_1_reference=request.r3_1_reference,
        policy_version=request.policy_version, untracked_policy=request.repository.untracked_policy,
    )
    fingerprint = identity.fingerprint
    obligations = derive_change_obligations(envelope)
    reconciliation = reconcile(snapshot, request.r3_1_reference, obligations, fingerprint)
    evidence = (
        f"r1-event:{request.correlation_id}", f"r3.2-derivation:r3.2:derivation:{fingerprint}",
        f"r3.2-reconciliation:{reconciliation.reconciliation_id}", f"provider-envelope:{canonical_sha256(envelope.to_dict())}",
        f"r3.1-snapshot:{request.r3_1_reference.snapshot_id}",
    )
    derivation = ChangeImpactDerivation(
        derivation_version_id=f"r3.2:derivation:{fingerprint}", identity=identity, code_intelligence=envelope,
        change_obligations=obligations, r3_1_reference=request.r3_1_reference, evidence_references=evidence,
        correlation_id=request.correlation_id, idempotency_key=request.idempotency_key, requested_by=request.requested_by,
    )
    return derivation, reconciliation
