from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import KnowledgeRelation, KnowledgeScopeIdentity, R3E1Error
from .retrieval import KnowledgeRetrievalResult, build_r31_anchor


@dataclass(frozen=True)
class VerticalSliceCheck:
    check_id: str
    status: str
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "status": self.status, "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class VerticalSliceClosure:
    status: str
    scope_identity: KnowledgeScopeIdentity
    anchor_digest: str
    checks: tuple[VerticalSliceCheck, ...]
    closure_receipt: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope_identity": self.scope_identity.to_dict(),
            "anchor_digest": self.anchor_digest,
            "checks": [item.to_dict() for item in self.checks],
            "closure_receipt": dict(self.closure_receipt),
        }


def execute_vertical_slice(
    *,
    snapshot: Any,
    obligation: Any,
    result: KnowledgeRetrievalResult,
    requested_scope: KnowledgeScopeIdentity,
    context_handoff: Mapping[str, Any] | None = None,
) -> VerticalSliceClosure:
    expected_anchor = build_r31_anchor(snapshot, obligation)
    checks: list[VerticalSliceCheck] = []

    def check(check_id: str, condition: bool, evidence: Mapping[str, Any], reason: str = "PASS") -> None:
        checks.append(VerticalSliceCheck(check_id, "PASS" if condition else "GAP", {**dict(evidence), "reason": reason if condition else "VISIBLE_GAP"}))

    check("VS-01", result.anchor_digest == expected_anchor["anchor_digest"], {
        "snapshot_id": snapshot.snapshot_id,
        "obligation_id": obligation.obligation_id,
        "anchor_digest": result.anchor_digest,
    })
    check("VS-02", bool(obligation.source_provenance) and all(item.get("source_digest") for item in expected_anchor["source_provenance"]), {
        "source_provenance_count": len(obligation.source_provenance),
        "source_bundle_digest": expected_anchor["source_bundle_digest"],
    })

    by_type = {
        str((fact.metadata or {}).get("endpoint_type")): fact
        for fact in result.facts
        if (fact.metadata or {}).get("endpoint_type")
    }
    chain = (
        ("VS-03", "FRONTEND_PAGE"),
        ("VS-04", "API_DEPENDENCY"),
        ("VS-05", "BACKEND_CODE"),
        ("VS-06", "DATABASE_DATA"),
        ("VS-07", "JOURNEY_STATE"),
    )
    for check_id, endpoint_type in chain:
        fact = by_type.get(endpoint_type)
        check(check_id, fact is not None, {
            "endpoint_type": endpoint_type,
            "fact_id": fact.fact_id if fact else None,
        })

    expected_semantics = ("ROUTES_TO", "CALLS", "IMPLEMENTS", "READS", "TRANSITIONS_TO")
    actual_semantics = tuple(item.semantic for item in result.relations)
    check("VS-08", all(item in actual_semantics for item in expected_semantics), {
        "required_semantics": list(expected_semantics),
        "actual_semantics": list(actual_semantics),
    })
    check("VS-09", all(
        fact.scope_identity == requested_scope and version.scope_identity == requested_scope and version.status in {
            "SOURCE_VERIFIED", "RUNTIME_VERIFIED", "USER_VERIFIED",
        }
        for fact, version in zip(result.facts, result.versions)
    ), {
        "fact_count": len(result.facts),
        "version_count": len(result.versions),
        "requested_scope": requested_scope.to_dict(),
    })
    check("VS-10", all(
        version.source_ref_ids and version.freshness_id and all(
            source.scope_identity == version.scope_identity for source in result.source_refs if source.source_ref_id in version.source_ref_ids
        )
        for version in result.versions
    ) and all(relation.source_ref_ids for relation in result.relations), {
        "source_ref_count": len(result.source_refs),
        "freshness_count": len(result.freshness),
    })
    selected_bytes = int(result.retrieval_receipt.get("selected_bytes", 0))
    selected_items = int(result.retrieval_receipt.get("selected_item_count", 0))
    check("VS-11", selected_items <= 24 and selected_bytes <= 12288, {
        "selected_item_count": selected_items,
        "selected_bytes": selected_bytes,
        "truncation": result.truncation,
    })
    handoff = dict(context_handoff or {})
    check("VS-12", bool(handoff) and int(handoff.get("knowledge_item_count", 0)) <= 24 and not handoff.get("permanent_context", False), {
        "knowledge_item_count": handoff.get("knowledge_item_count"),
        "session_ref": handoff.get("session_ref"),
        "permanent_context": handoff.get("permanent_context", False),
    })
    relation_scope_ok = all(
        relation.scope_identity == requested_scope
        and (
            all(endpoint.scope_identity == requested_scope for endpoint in (relation.from_ref, relation.to_ref))
            or bool(relation.cross_scope_provenance)
        )
        for relation in result.relations
    )
    check("VS-13", all(fact.scope_identity == requested_scope for fact in result.facts) and relation_scope_ok, {
        "requested_scope": requested_scope.to_dict(),
        "mission_task_session_are_owner": False,
    })

    status = "PASS" if all(item.status == "PASS" for item in checks) else "INCOMPLETE"
    receipt = {
        "anchor": expected_anchor,
        "scope_identity": requested_scope.to_dict(),
        "fact_ids": [item.fact_id for item in result.facts],
        "version_ids": [item.version_id for item in result.versions],
        "relation_ids": [item.relation_id for item in result.relations],
        "source_ref_ids": [item.source_ref_id for item in result.source_refs],
        "retrieval_result_digest": result.result_digest,
        "context_handoff": handoff,
        "closure_digest": canonical_sha256({
            "anchor": expected_anchor,
            "fact_ids": [item.fact_id for item in result.facts],
            "version_ids": [item.version_id for item in result.versions],
            "relation_ids": [item.relation_id for item in result.relations],
        }),
    }
    return VerticalSliceClosure(status, requested_scope, result.anchor_digest, tuple(checks), receipt)
