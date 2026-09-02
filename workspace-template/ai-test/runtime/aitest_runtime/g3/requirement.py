from __future__ import annotations
from typing import Any, Mapping
from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.r3_1.contracts import DerivationRequest
from aitest_runtime.r3_1.service import R31ApplicationService
from aitest_runtime.r3_2.contracts import R31Reference
from aitest_runtime.r3_2.engine import r31_provenance_bundle_digest
from .contracts import validate_requirement_semantics

_CATEGORY_TO_OBLIGATION = {
    "business_rules": "BUSINESS_RULE", "field_data_rules": "BUSINESS_RULE", "state_transitions": "STATE_TRANSITION",
    "positive_paths": "BUSINESS_OPERATION", "negative_paths": "BUSINESS_OPERATION", "exception_paths": "BUSINESS_OPERATION",
    "boundary_rules": "BUSINESS_RULE", "permission_rules": "BUSINESS_RULE", "cross_system_flows": "BUSINESS_OPERATION",
    "acceptance_criteria": "ACCEPTANCE_CRITERION", "non_functional_risks": "REQUIREMENT",
}

def _item_text(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, str) and value.strip(): return value.strip(), {}
    if isinstance(value, Mapping):
        text = value.get("text") or value.get("rule") or value.get("description") or value.get("criterion") or value.get("flow")
        if isinstance(text, str) and text.strip(): return text.strip(), dict(value)
    raise RuntimeError("G3_REQUIREMENT_ITEM_INVALID", "semantic items require text")


def derive_requirement_intelligence(runtime: Any, mission_id: str, scope_identity: str, semantics: Mapping[str, Any], *, requested_by: Mapping[str, str] | None = None, correlation_id: str = "g3-requirement") -> dict[str, Any]:
    data = validate_requirement_semantics(semantics)
    sources_by_id: dict[str, dict[str, Any]] = {}
    source_refs = data["source_refs"]
    for index, ref in enumerate(source_refs, 1):
        if isinstance(ref, str): ref = {"source_id": ref, "source_kind": "REQUIREMENT", "revision": "UNKNOWN", "locator": ref}
        if not isinstance(ref, Mapping): raise RuntimeError("G3_REQUIREMENT_PROVENANCE_REQUIRED", "source_ref must be string/object")
        sid = str(ref.get("source_id") or f"source-{index}")
        kind = str(ref.get("source_kind") or "REQUIREMENT").upper()
        if kind not in {"REQUIREMENT", "SST", "DESIGN"}: raise RuntimeError("G3_REQUIREMENT_SOURCE_KIND_INVALID", kind)
        locator = str(ref.get("locator") or sid); revision = str(ref.get("revision") or "UNKNOWN")
        sources_by_id[sid] = {"source_id": sid, "source_kind": kind, "revision": revision, "provenance": {"locator": locator, "source_digest": str(ref.get("source_digest") or canonical_sha256(dict(ref))), "metadata": {"origin": "G3_REQUIREMENT_ANALYST"}}, "items": []}
    default_source = next(iter(sources_by_id.values()))
    obligation_refs: list[str] = []
    traceability: list[dict[str, Any]] = []
    for category, obligation_type in _CATEGORY_TO_OBLIGATION.items():
        for index, raw in enumerate(data[category], 1):
            text, metadata = _item_text(raw)
            source_id = str(metadata.pop("source_id", default_source["source_id"]))
            source = sources_by_id.get(source_id)
            if source is None: raise RuntimeError("G3_REQUIREMENT_PROVENANCE_REQUIRED", f"unknown source_id: {source_id}")
            oid = str(metadata.pop("obligation_id", f"{scope_identity}:{category}:{index}"))
            obligation_refs.append(oid)
            source["items"].append({
                "item_id": f"{category}:{index}", "obligation_id": oid, "obligation_type": obligation_type, "text": text,
                "metadata": {"g3_semantic_kind": category, **metadata}, "source_status": "AVAILABLE", "source_gap_kinds": [],
                "provenance": {"locator": source["provenance"]["locator"], "metadata": {"semantic_kind": category}},
            })
            # Explicit semantic-to-code links are planning evidence, not actual coverage.
            # Preserve them as R3.1 traceability so frozen downstream R3.3 can select
            # code-aware test layers without inventing relations.
            for code_ref in metadata.get("code_refs") or []:
                if str(code_ref).strip():
                    traceability.append({
                        "obligation_id": oid,
                        "asset_id": str(code_ref),
                        "relation_type": "RELATES_TO_CHANGED_CODE",
                        "mapping_state": "MAPPED",
                        "provenance": {"locator": source["provenance"]["locator"], "metadata": {"source": "G3_EXPLICIT_CODE_REF"}},
                    })
    if not obligation_refs:
        raise RuntimeError("G3_REQUIREMENT_OBLIGATION_EMPTY", "semantic model produced no test obligations")
    bundle = {"sources": list(sources_by_id.values()), "traceability": traceability, "coverage": []}
    digest = canonical_sha256(bundle)
    request = DerivationRequest(
        mission_id=mission_id, scope_identity=scope_identity, source_bundle_digest=digest, source_bundle=bundle,
        derivation_policy_version="g3.requirement-to-r3.1.v1", idempotency_key=f"g3-r31:{canonical_sha256({'scope':scope_identity,'digest':digest})[:24]}",
        requested_by=requested_by or {"type": "AGENT", "id": "aitest-requirement-analyst"}, correlation_id=correlation_id,
    )
    result = R31ApplicationService(runtime).derive(request)
    if not result.ok or result.derivation is None:
        raise RuntimeError("G3_R31_DERIVATION_FAILED", result.error_code or "unknown")
    state = R31ApplicationService(runtime).runtime.replay_composed(mission_id).extension_state("r3_1_requirement_coverage_traceability")
    snapshot = state.snapshot(result.derivation.coverage_snapshot_id)
    if snapshot is None: raise RuntimeError("G3_R31_SNAPSHOT_MISSING", result.derivation.coverage_snapshot_id)
    reference = R31Reference(result.derivation.derivation_version_id, snapshot.snapshot_id, result.derivation.derivation_fingerprint, digest, r31_provenance_bundle_digest(snapshot))
    unknowns = []
    for index, raw in enumerate(data["unknowns"], 1):
        if isinstance(raw, str): unknowns.append({"gap_id": f"knowledge-gap:{scope_identity}:{index}", "question": raw, "status": "OPEN"})
        elif isinstance(raw, Mapping): unknowns.append({"gap_id": str(raw.get("gap_id") or f"knowledge-gap:{scope_identity}:{index}"), "question": str(raw.get("question") or raw.get("text") or "UNKNOWN_FACT"), "status": "OPEN", **{str(k):v for k,v in raw.items() if k not in {"gap_id","question"}}})
    return {"semantic_model": data, "r3_1_reference": reference.to_dict(), "r3_1_derivation": result.derivation.to_dict(), "knowledge_gaps": unknowns, "obligation_refs": obligation_refs}
