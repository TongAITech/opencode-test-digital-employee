from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, canonical_sha256

from .contracts import (
    ACCEPTED_OBLIGATION_TYPES,
    ACCEPTED_SOURCE_KINDS,
    DERIVATION_CREATED,
    DERIVATION_REUSED,
    DERIVE_REQUIREMENT_COVERAGE,
    MAPPING_STATES,
    CoverageGap,
    CoverageRelation,
    DerivationRequest,
    R31Error,
    R31State,
    SourceProvenance,
    TestCoverageObligation,
)


def _state(composed: ComposedRuntimeState) -> R31State:
    value = composed.extension_state("r3_1_requirement_coverage_traceability")
    if not isinstance(value, R31State):
        raise R31Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.1 extension state")
    return value


def _payload(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be an array")
    return list(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _canonical_digest(value: Any) -> str:
    return canonical_sha256(value)


def _source_provenance(
    source: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    item_id: str,
    source_bundle_digest: str,
) -> SourceProvenance:
    source_id = _text(source.get("source_id"), "source.source_id")
    source_kind = _text(source.get("source_kind"), "source.source_kind")
    if source_kind not in ACCEPTED_SOURCE_KINDS:
        raise R31Error("R3_1_SOURCE_KIND_UNSUPPORTED", f"unsupported source kind: {source_kind}")
    source_revision = _text(source.get("revision"), "source.revision")
    source_proof = _mapping(source.get("provenance"), "source.provenance")
    item_proof = _mapping(item.get("provenance", {}), "item.provenance")
    locator = _text(item_proof.get("locator") or source_proof.get("locator"), "source provenance locator")
    source_digest = _text(
        item_proof.get("source_digest") or source_proof.get("source_digest") or source_bundle_digest,
        "source provenance digest",
    )
    metadata = dict(source_proof.get("metadata") or {})
    metadata.update(dict(item_proof.get("metadata") or {}))
    return SourceProvenance(
        source_id=source_id,
        source_kind=source_kind,
        revision=source_revision,
        locator=locator,
        item_id=item_id,
        source_digest=source_digest,
        source_bundle_digest=source_bundle_digest,
        metadata=metadata,
    )


def _extract_obligations(request: DerivationRequest) -> tuple[dict[str, Any], ...]:
    bundle = _mapping(request.source_bundle, "source_bundle")
    if _canonical_digest(bundle) != request.source_bundle_digest:
        raise R31Error("R3_1_SOURCE_DIGEST_MISMATCH", "source_bundle_digest does not match canonical source_bundle")
    sources = _array(bundle.get("sources"), "source_bundle.sources")
    if not sources:
        raise R31Error("R3_1_DENOMINATOR_EMPTY", "source bundle must contain at least one source")
    seen_sources: set[str] = set()
    obligations: list[dict[str, Any]] = []
    for raw_source in sources:
        source = _mapping(raw_source, "source")
        source_id = _text(source.get("source_id"), "source.source_id")
        if source_id in seen_sources:
            raise R31Error("R3_1_SOURCE_IDENTITY_CONFLICT", f"duplicate source_id: {source_id}")
        seen_sources.add(source_id)
        source_kind = _text(source.get("source_kind"), "source.source_kind")
        if source_kind not in ACCEPTED_SOURCE_KINDS:
            raise R31Error("R3_1_SOURCE_KIND_UNSUPPORTED", f"unsupported source kind: {source_kind}")
        items = _array(source.get("items"), f"source[{source_id}].items")
        for raw_item in items:
            item = _mapping(raw_item, f"source[{source_id}].item")
            item_id = _text(item.get("item_id"), f"source[{source_id}].item_id")
            obligation_id = _text(item.get("obligation_id") or f"{source_id}:{item_id}", "obligation_id")
            obligation_type = _text(item.get("obligation_type"), f"obligation[{obligation_id}].obligation_type")
            if obligation_type not in ACCEPTED_OBLIGATION_TYPES:
                raise R31Error("R3_1_OBLIGATION_TYPE_UNSUPPORTED", f"unsupported obligation type: {obligation_type}")
            text = _text(item.get("text"), f"obligation[{obligation_id}].text")
            provenance = _source_provenance(
                source, item, item_id=item_id, source_bundle_digest=request.source_bundle_digest,
            )
            obligations.append({
                "obligation_id": obligation_id,
                "obligation_type": obligation_type,
                "text": text,
                "source_provenance": (provenance,),
                "metadata": dict(item.get("metadata") or {}),
                "source_status": item.get("source_status", "AVAILABLE"),
                "source_gap_kinds": tuple(item.get("source_gap_kinds") or ()),
            })
    if not obligations:
        raise R31Error("R3_1_DENOMINATOR_EMPTY", "source bundle produced no requirement obligations")
    identities = [item["obligation_id"] for item in obligations]
    if len(identities) != len(set(identities)):
        raise R31Error("R3_1_OBLIGATION_IDENTITY_CONFLICT", "obligation identities must be unique")
    return tuple(obligations)


def _relations(
    bundle: Mapping[str, Any],
    obligations: tuple[dict[str, Any], ...],
) -> dict[str, tuple[CoverageRelation, ...]]:
    known = {item["obligation_id"]: item for item in obligations}
    by_obligation: dict[str, list[CoverageRelation]] = defaultdict(list)
    seen: set[str] = set()
    for raw in _array(bundle.get("traceability", []), "source_bundle.traceability"):
        value = _mapping(raw, "traceability relation")
        obligation_id = _text(value.get("obligation_id"), "traceability.obligation_id")
        if obligation_id not in known:
            raise R31Error("R3_1_TRACEABILITY_REFERENCE_INVALID", f"mapping references unknown obligation: {obligation_id}")
        asset_id = _text(value.get("asset_id"), "traceability.asset_id")
        relation_type = _text(value.get("relation_type"), "traceability.relation_type")
        mapping_state = _text(value.get("mapping_state"), "traceability.mapping_state")
        if mapping_state not in {"MAPPED", "PARTIAL"}:
            raise R31Error("R3_1_MAPPING_STATE_INVALID", "traceability relation must be MAPPED or PARTIAL")
        relation_id = _text(
            value.get("relation_id") or _canonical_digest({
                "obligation_id": obligation_id, "asset_id": asset_id,
                "relation_type": relation_type, "mapping_state": mapping_state,
                "metadata": value.get("metadata") or {},
            }),
            "traceability.relation_id",
        )
        if relation_id in seen:
            raise R31Error("R3_1_TRACEABILITY_IDENTITY_CONFLICT", f"duplicate relation_id: {relation_id}")
        seen.add(relation_id)
        by_obligation[obligation_id].append(
            CoverageRelation(
                relation_id=relation_id, obligation_id=obligation_id, asset_id=asset_id,
                relation_type=relation_type, mapping_state=mapping_state,
                source_provenance=known[obligation_id]["source_provenance"],
                metadata=value.get("metadata") or {},
            )
        )
    return {key: tuple(value) for key, value in by_obligation.items()}


def _coverage_inputs(bundle: Mapping[str, Any], known: set[str]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in _array(bundle.get("coverage", []), "source_bundle.coverage"):
        value = _mapping(raw, "coverage assertion")
        obligation_id = _text(value.get("obligation_id"), "coverage.obligation_id")
        if obligation_id not in known:
            raise R31Error("R3_1_COVERAGE_REFERENCE_INVALID", f"coverage references unknown obligation: {obligation_id}")
        if obligation_id in result:
            raise R31Error("R3_1_COVERAGE_IDENTITY_CONFLICT", f"duplicate coverage assertion: {obligation_id}")
        if "covered" not in value or not isinstance(value["covered"], bool):
            raise R31Error("R3_1_COVERAGE_ASSERTION_INVALID", f"coverage.covered must be boolean: {obligation_id}")
        result[obligation_id] = value
    return result


def _gap(
    obligation_id: str,
    kind: str,
    reason: str,
    provenance: tuple[SourceProvenance, ...],
) -> CoverageGap:
    if kind not in {"UNCOVERED", "REQUIREMENT_CODE_GAP", "SOURCE_INCOMPLETE", "TRACEABILITY_CONFLICT", "SOURCE_UNAVAILABLE"}:
        raise R31Error("R3_1_COVERAGE_GAP_INVALID", f"invalid CoverageGap kind: {kind}")
    return CoverageGap(
        gap_id=_canonical_digest({"obligation_id": obligation_id, "kind": kind, "reason": reason}),
        obligation_id=obligation_id, kind=kind, reason=_text(reason, "coverage gap reason"),
        source_provenance=provenance,
    )


def _gaps(
    item: Mapping[str, Any],
    coverage: Mapping[str, Any] | None,
    relations: tuple[CoverageRelation, ...],
) -> tuple[CoverageGap, ...]:
    obligation_id = item["obligation_id"]
    provenance = item["source_provenance"]
    requested: list[tuple[str, str]] = []
    if coverage is None or coverage.get("covered") is False:
        requested.append(("UNCOVERED", "no accepted test asset demonstrates sufficient coverage"))
    if coverage is not None:
        for kind in coverage.get("gap_kinds") or ():
            requested.append((str(kind), str(coverage.get("reason") or f"coverage assertion reports {kind}")))
    for kind in item.get("source_gap_kinds") or ():
        requested.append((str(kind), f"source-derived obligation reports {kind}"))
    source_status = str(item.get("source_status") or "AVAILABLE")
    if source_status == "INCOMPLETE":
        requested.append(("SOURCE_INCOMPLETE", "authoritative source item is incomplete"))
    elif source_status == "UNAVAILABLE":
        requested.append(("SOURCE_UNAVAILABLE", "authoritative source item is unavailable"))
    for relation in relations:
        for kind in relation.metadata.get("gap_kinds") or ():
            requested.append((str(kind), f"traceability relation reports {kind}"))
    deduped: dict[str, CoverageGap] = {}
    for kind, reason in requested:
        gap = _gap(obligation_id, kind, reason, provenance)
        deduped[kind] = gap
    return tuple(deduped[key] for key in sorted(deduped))


def _mapping_state(relations: tuple[CoverageRelation, ...]) -> str:
    if not relations:
        return "UNMAPPED"
    states = {item.mapping_state for item in relations}
    if states == {"MAPPED"}:
        return "MAPPED"
    return "PARTIAL"


def derive_payload(request: DerivationRequest) -> dict[str, Any]:
    identity = request.identity()
    obligations = _extract_obligations(request)
    bundle = _mapping(request.source_bundle, "source_bundle")
    relation_map = _relations(bundle, obligations)
    coverage_map = _coverage_inputs(bundle, {item["obligation_id"] for item in obligations})
    result: list[TestCoverageObligation] = []
    for item in obligations:
        relations = relation_map.get(item["obligation_id"], ())
        result.append(
            TestCoverageObligation(
                obligation_id=item["obligation_id"], obligation_type=item["obligation_type"], text=item["text"],
                source_provenance=item["source_provenance"], mapping_state=_mapping_state(relations),
                coverage_gaps=_gaps(item, coverage_map.get(item["obligation_id"]), relations),
                coverage_relations=relations, metadata=item["metadata"],
            )
        )
    obligations_tuple = tuple(result)
    fingerprint = identity.fingerprint
    version_id = f"r3.1:derivation:{fingerprint}"
    snapshot_id = f"r3.1:snapshot:{fingerprint}"
    evidence_references = (
        f"r1-event:{request.correlation_id}",
        f"r3.1-derivation:{version_id}",
        f"r3.1-snapshot:{snapshot_id}",
        f"source-bundle:{request.source_bundle_digest}",
    )
    return {
        "derivation": {
            "derivation_version_id": version_id,
            "identity": identity.to_dict(),
            "derivation_fingerprint": fingerprint,
            "obligation_denominator_count": len(obligations_tuple),
            "obligations": [item.to_dict() for item in obligations_tuple],
            "coverage_snapshot_id": snapshot_id,
            "evidence_references": list(evidence_references),
            "correlation_id": request.correlation_id,
            "idempotency_key": request.idempotency_key,
            "requested_by": dict(request.requested_by),
        },
        "snapshot": {
            "snapshot_id": snapshot_id,
            "derivation_version_id": version_id,
            "identity": identity.to_dict(),
            "derivation_fingerprint": fingerprint,
            "denominator_count": len(obligations_tuple),
            "obligations": [item.to_dict() for item in obligations_tuple],
        },
    }


def handle(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type != DERIVE_REQUIREMENT_COVERAGE:
        raise R31Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R3.1 command: {command.type}")
    request = DerivationRequest.from_payload(
        command.payload, command_mission_id=command.mission_id, correlation_id=command.correlation_id,
    )
    if command.idempotency_key != request.idempotency_key:
        raise R31Error("R3_1_IDEMPOTENCY_KEY_MISMATCH", "command idempotency_key must match derivation request")
    derived = derive_payload(request)
    fingerprint = derived["derivation"]["derivation_fingerprint"]
    state = _state(composed)
    existing = state.derivation(fingerprint)
    if existing is not None:
        return [
            PendingEvent(
                DERIVATION_REUSED,
                "R3_1_DERIVATION_REUSE",
                f"r3.1:reuse:{command.command_id}",
                {
                    "derivation_version_id": existing.derivation_version_id,
                    "derivation_fingerprint": fingerprint,
                    "idempotency_key": request.idempotency_key,
                },
                session_id=command.session_id,
            )
        ]
    return [
        PendingEvent(
            DERIVATION_CREATED,
            "R3_1_DERIVATION",
            derived["derivation"]["derivation_version_id"],
            derived,
            session_id=command.session_id,
        )
    ]


class R31CommandContribution:
    def handle(self, command, composed):
        return handle(command, composed)
