"""WB-E01 pre-B06 read-only scope-to-R1 projection PROTOTYPE.

Design-only adapter: no HTTP routes, no SQL storage, no principal authority,
no commands, no writes, no SSE subscription, no NodeGate admission.
The real WB-E01 product implementation is BLOCKED_DEPENDENCY_B06.

The authoritative B06 service MUST implement true source-verified
Requirement/SystemVersion/SST joins and authorization before this
projection can be integrated. The old rc7_admin fuzzy filters cannot
be used as a substitute.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Callable, Dict, Mapping

from .e_contract_oracle import ContractRejection


def _expect(ok: bool, code: str) -> None:
    if not ok:
        raise ContractRejection(code)


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_ref(row: Mapping[str, Any], key: str, source_revision_key: str) -> str:
    """Source link must be explicit and verified, never derived from names."""
    source = row.get(key)
    _expect(isinstance(source, Mapping), "SOURCE_VERIFIED_LINK_REQUIRED")
    _expect(_nonempty(source.get("source_link_ref"))
            and _nonempty(source.get(source_revision_key)),
            "SOURCE_VERIFIED_LINK_REQUIRED")
    return str(source["source_link_ref"])


def normalize_b06_scope(scope: Mapping[str, Any], *, project_id: str,
                        batch_id: str) -> Dict[str, Any]:
    """Validate a B06-like response without making it authoritative.

    This is a DTO/protocol check, NOT a permission check or B06 implementation.
    Must only be called after a trusted service has independently authenticated
    principal and authorized project, batch, and query scope. B06 does not own
    Mission membership; that binding is checked against explicit R1 fields below.
    """
    _expect(isinstance(scope, Mapping), "SCOPE_SOURCE_UNAVAILABLE")
    _expect(_nonempty(project_id) and _nonempty(batch_id), "INVALID_SCOPE")
    _expect(scope.get("project_id") == project_id, "FORBIDDEN")
    _expect(scope.get("batch_id") == batch_id, "ILLEGAL_ASSOCIATION")
    _expect(_nonempty(scope.get("release_date")) and
            len(scope["release_date"]) == 10 and
            scope["release_date"][4] == "-" and scope["release_date"][7] == "-",
            "INVALID_BUSINESS_DATE")
    try:
        _expect(date.fromisoformat(scope["release_date"]).isoformat()
                == scope["release_date"], "INVALID_BUSINESS_DATE")
    except ValueError as exc:
        raise ContractRejection("INVALID_BUSINESS_DATE") from exc
    _expect(_positive_int(scope.get("relation_revision")) and
            _positive_int(scope.get("access_scope_revision")),
            "SCOPE_REVISION_UNAVAILABLE")
    # B06 is a project+batch business-scope service, not the Mission registry.
    # An empty relation set is not a successful empty scope; B must return 422.
    raw = scope.get("records")
    _expect(isinstance(raw, (tuple, list)), "SOURCE_VERIFIED_RELATIONS_REQUIRED")
    _expect(len(raw) > 0, "ILLEGAL_ASSOCIATION")
    source_refs = scope.get("source_refs")
    _expect(isinstance(source_refs, (tuple, list)) and len(source_refs) > 0
            and all(_nonempty(item) for item in source_refs),
            "SOURCE_REFS_REQUIRED")
    source_refs = [str(item) for item in source_refs]
    _expect(len(set(source_refs)) == len(source_refs), "SOURCE_REFS_DUPLICATE")
    warnings = scope.get("warnings", [])
    gaps = scope.get("gap_indicators", [])
    _expect(isinstance(warnings, (tuple, list))
            and all(_nonempty(item) for item in warnings)
            and isinstance(gaps, (tuple, list))
            and all(_nonempty(item) for item in gaps),
            "SCOPE_DIAGNOSTICS_INVALID")
    next_cursor = scope.get("next_page_cursor")
    _expect(next_cursor is None or _nonempty(next_cursor),
            "PAGINATION_CURSOR_INVALID")
    pagination_complete = ("next_page_cursor" in scope and next_cursor is None)
    relations = []
    seen = set()
    for row in raw:
        _expect(isinstance(row, Mapping), "SOURCE_VERIFIED_RELATIONS_REQUIRED")
        _expect(row.get("project_id") == project_id
                and row.get("batch_id") == batch_id, "CROSS_BATCH_ASSOCIATION")
        req = row.get("requirement_id")
        ver = row.get("system_version_id")
        sst = row.get("sst_id")
        _expect(_nonempty(req) and _nonempty(ver), "INVALID_RELATION_ID")
        rv_ref = _source_ref(row, "source_verified_requirement_version",
                             "source_revision")
        _expect(rv_ref in source_refs, "SOURCE_REFERENCE_NOT_IN_SCOPE")
        split = row.get("split_state")
        _expect(split in {"SPLIT", "UNSPLIT"}, "INVALID_SPLIT_STATE")
        if split == "UNSPLIT":
            _expect(sst is None and row.get("source_verified_link") is None,
                    "UNSPLIT_MUST_NOT_INVENT_SST")
            sst_ref = None
        else:
            _expect(_nonempty(sst), "SPLIT_REQUIRES_SST")
            sst_ref = _source_ref(row, "source_verified_link",
                                  "verified_source_revision")
            _expect(sst_ref in source_refs, "SOURCE_REFERENCE_NOT_IN_SCOPE")
        identity = (project_id, batch_id, req, ver, sst)
        _expect(identity not in seen, "DUPLICATE_RELATION")
        seen.add(identity)
        relations.append({
            "project_id": project_id, "batch_id": batch_id,
            "requirement_id": req, "system_version_id": ver,
            "sst_id": sst, "split_state": split,
            "source_verified_requirement_version_ref": rv_ref,
            "source_verified_link_ref": sst_ref,
        })
    return {
        "project_id": project_id, "batch_id": batch_id,
        "release_date": scope["release_date"],
        "relation_revision": scope["relation_revision"],
        "access_scope_revision": scope["access_scope_revision"],
        "source_refs": source_refs,
        "warnings": [str(item) for item in warnings],
        "gap_indicators": [str(item) for item in gaps],
        "next_page_cursor": next_cursor,
        "pagination_complete": pagination_complete,
        "records": relations,
    }


def r1_preview(b06_authorized_scope: Mapping[str, Any],
               r1_mission_overview: Mapping[str, Any], *,
               project_id: str, batch_id: str, mission_id: str) -> Dict[str, Any]:
    """DTO projection only, never a confirmed execution result.

    B06 response must already have been authorized by the real service.
    No evidence hash is assumed validated and no NodeGate is inferred
    from task status, model text, a screenshot or test case counts.
    """
    scope = normalize_b06_scope(b06_authorized_scope,
                                project_id=project_id, batch_id=batch_id)
    _expect(isinstance(r1_mission_overview, Mapping), "TRUTH_SOURCE_UNAVAILABLE")
    mission = r1_mission_overview.get("mission")
    _expect(isinstance(mission, Mapping), "TRUTH_SOURCE_UNAVAILABLE")
    _expect(mission.get("mission_id") == mission_id, "R1_MISSION_MISMATCH")
    # RC7.2 inherited Mission may lack project_id and batch_id; unresolved
    # bindings must never be back-filled by parsing release_id or name.
    _expect(mission.get("project_id") == project_id
            and mission.get("batch_id") == batch_id,
            "R1_MISSION_SCOPE_UNRESOLVED")
    related = r1_mission_overview.get("related")
    _expect(isinstance(related, Mapping), "TRUTH_SOURCE_UNAVAILABLE")
    workitems = []
    attempts = []
    evidence = []
    for name, sink, id_field in (
        ("tasks", workitems, "task_id"),
        ("executions", attempts, "attempt_id"),
        ("evidence", evidence, "evidence_id"),
    ):
        raw = related.get(name, [])
        _expect(isinstance(raw, list), "R1_MALFORMED_COLLECTION")
        seen = set()
        for row in raw:
            _expect(isinstance(row, Mapping)
                    and _nonempty(row.get(id_field))
                    and row.get("mission_id") == mission_id,
                    "R1_UNVERIFIED_LINEAGE")
            key = row[id_field]
            _expect(key not in seen, "R1_DUPLICATE_ID")
            seen.add(key)
            item = {"id": key, "mission_id": mission_id,
                    "source_ref": "r1:%s:%s" % (name, key)}
            if name == "evidence":
                item["integrity"] = "UNVERIFIED_NO_CONTENT_READ"
                item["hash_declared"] = _nonempty(row.get("content_hash"))
            elif name == "executions":
                item["result"] = "UNKNOWN_UNQUALIFIED"
                item["trace_status"] = "UNRESOLVED_WITHOUT_CANONICAL_BINDING"
            else:
                item["status"] = "READ_ONLY_UNQUALIFIED"
            sink.append(item)
    r1_source_ref = "rc7_admin:mission_overview_scoped:%s" % mission_id
    combined_source_refs = list(scope["source_refs"])
    if r1_source_ref not in combined_source_refs:
        combined_source_refs.append(r1_source_ref)
    gap_indicators = list(scope["gap_indicators"])
    if not scope["pagination_complete"]:
        gap_indicators.append("B06_SCOPE_PAGINATION_INCOMPLETE")
    return {
        **deepcopy(scope),
        "mission_id": mission_id,
        "truth_revision": None,
        "as_of": None,
        "source_refs": combined_source_refs,
        "scope_complete": scope["pagination_complete"],
        "workitems": workitems,
        "attempts": attempts,
        "evidence": evidence,
        "nodegate": {"decision": "UNKNOWN_NOT_READ_FROM_CANONICAL_NODEGATE"},
        "release_decision": "HOLD",
        "data_quality": "PROTOTYPE_UNQUALIFIED",
        "gap_indicators": gap_indicators + [
            "B06_IMPLEMENTATION_QA_REQUIRED",
            "HOST_PRINCIPAL_AUTHORIZATION_REQUIRED",
            "R1_TRUTH_REVISION_AND_CANONICAL_NODEGATE_UNAVAILABLE",
            "ATTEMPT_CANONICAL_ETU_WORKITEM_LEASE_LINK_REQUIRED",
            "EVIDENCE_CONTENT_HASH_VERIFICATION_REQUIRED",
        ],
    }


def read_scoped_r1_mission_overview(
    projection: Any, *, project_id: str, batch_id: str, mission_id: str,
) -> Mapping[str, Any]:
    """Require a scope-first R1 port; never fall back to mission_id-only reads.

    The port must resolve only the Mission identity first, compare its explicit
    project/batch binding, and load related details only after that match.
    """
    _expect(projection is not None, "TRUTH_SOURCE_UNAVAILABLE")
    method = getattr(projection, "mission_overview_scoped", None)
    _expect(callable(method), "R1_SCOPED_READ_UNAVAILABLE")
    try:
        overview = method(
            mission_id=mission_id, project_id=project_id, batch_id=batch_id)
    except ContractRejection:
        raise
    except Exception as exc:
        # The legacy AdminProjection reports contract codes as RuntimeError text.
        if str(exc) == "R1_MISSION_SCOPE_UNRESOLVED":
            raise ContractRejection("R1_MISSION_SCOPE_UNRESOLVED") from exc
        raise ContractRejection("TRUTH_SOURCE_UNAVAILABLE") from exc
    _expect(isinstance(overview, Mapping), "TRUTH_SOURCE_UNAVAILABLE")
    return overview


def r1_preview_from_legacy_admin(
    authorized_b06_fetch: Callable[[str, str], Mapping[str, Any]],
    legacy_admin: Any, *,
    project_id: str, batch_id: str, mission_id: str,
) -> Dict[str, Any]:
    """Integration seam only; requires real B06/Host before ever exposing.

    The injected B06 port MUST be bound by server-side DSH Host middleware to the
    authenticated request context; it accepts project+batch only, never a principal
    from a browser/body argument. After B06 authorization, R1 must expose a scoped
    read port: resolve minimal Mission identity, verify exact project+batch, then
    load related details. The old mission_id-only overview is never a fallback.
    A fixture cannot authenticate production users or prove Host middleware wiring.
    """
    _expect(callable(authorized_b06_fetch), "SCOPE_SOURCE_UNAVAILABLE")
    _expect(_nonempty(project_id) and _nonempty(batch_id)
            and _nonempty(mission_id), "INVALID_SCOPE")
    b06 = authorized_b06_fetch(project_id, batch_id)
    normalize_b06_scope(b06, project_id=project_id, batch_id=batch_id)
    # Do not invoke /api/missions/{id} over an unprotected network endpoint:
    # direct in-process R1-derived read only, after B06 confirms authorization.
    projection = getattr(legacy_admin, "projection", None)
    overview = read_scoped_r1_mission_overview(
        projection, project_id=project_id, batch_id=batch_id,
        mission_id=mission_id)
    return r1_preview(b06, overview, project_id=project_id,
                      batch_id=batch_id, mission_id=mission_id)
