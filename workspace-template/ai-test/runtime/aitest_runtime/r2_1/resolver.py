from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .. import truth
from ..common import now_iso
from ..storage import all_rows, jload, one
from .contracts import (
    CAPABILITY_AVAILABLE,
    CAPABILITY_BLOCKED,
    CAPABILITY_INVALID,
    CAPABILITY_STATUSES,
    CAPABILITY_UNAVAILABLE,
    CONTRACT_VERSION,
    FACT_CONFLICT,
    FACT_ERROR,
    FACT_KNOWN,
    FACT_NOT_CONFIGURED,
    FACT_UNKNOWN,
    FACT_STATUSES,
    RESOLUTION_BLOCKED,
    RESOLUTION_INVALID,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNAVAILABLE,
    SCOPE_ENVIRONMENT,
    SCOPE_PROJECT,
    SCOPE_REPOSITORY,
    SCOPE_TYPES,
    SNAPSHOT_KIND,
    IdempotencyConflict,
    R2_1Error,
    ResolutionRequest,
    canonical_json,
    normalize_status,
    sha256_digest,
    validate_secret_boundary,
)


_BLOCKING_FACT_STATUSES = FACT_STATUSES - {FACT_KNOWN}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _value(entry: Mapping[str, Any]) -> Any:
    if "value_or_reference" in entry:
        return entry["value_or_reference"]
    return entry.get("value")


def _source_refs(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("source_refs", entry.get("sources"))
    if raw is None:
        raw = entry.get("source_ref", entry.get("source"))
    if isinstance(raw, (list, tuple)):
        return _unique([str(item) for item in raw if item is not None])
    return [str(raw)] if raw is not None else []


def _scope(request: ResolutionRequest) -> dict[str, Any]:
    raw = dict(request.scope)
    scope_type = str(raw.get("type", raw.get("scope_type", ""))).upper()
    project_id = str(raw.get("project_id") or "").strip()
    if scope_type not in SCOPE_TYPES:
        raise R2_1Error("INVALID_SCOPE", "scope type must be PROJECT, ENVIRONMENT or REPOSITORY")
    if not project_id:
        raise R2_1Error("INVALID_SCOPE", "project_id is required")

    result: dict[str, Any] = {"type": scope_type, "project_id": project_id}
    environment_id = raw.get("environment_id")
    repository_id = raw.get("repository_id")
    if scope_type == SCOPE_ENVIRONMENT:
        if not str(environment_id or "").strip():
            raise R2_1Error("INVALID_SCOPE", "environment_id is required for ENVIRONMENT scope")
        result["environment_id"] = str(environment_id)
    elif scope_type == SCOPE_REPOSITORY:
        if not str(repository_id or "").strip():
            raise R2_1Error("INVALID_SCOPE", "repository_id is required for REPOSITORY scope")
        result["repository_id"] = str(repository_id)
    elif environment_id is not None or repository_id is not None:
        raise R2_1Error("INVALID_SCOPE", "PROJECT scope cannot carry environment_id or repository_id")
    return result


def _precedence_rank(precedence: Any, fact_key: str, attribute: str, source_ref: str) -> int | None:
    if isinstance(precedence, (list, tuple)):
        try:
            return list(precedence).index(source_ref)
        except ValueError:
            return None
    if not isinstance(precedence, Mapping):
        return None

    rule: Any = precedence.get(fact_key, precedence.get(attribute, precedence))
    if isinstance(rule, Mapping):
        value = rule.get(source_ref)
        return int(value) if isinstance(value, (int, float)) else None
    if isinstance(rule, (list, tuple)):
        try:
            return list(rule).index(source_ref)
        except ValueError:
            return None
    if isinstance(precedence.get(source_ref), (int, float)):
        return int(precedence[source_ref])
    return None


def _ranked_candidates(candidates: list[dict[str, Any]], precedence: Any, fact_key: str) -> list[tuple[int | None, int, dict[str, Any]]]:
    return [
        (
            _precedence_rank(precedence, fact_key, item["attribute"], item["source_refs"][0] if item["source_refs"] else ""),
            index,
            item,
        )
        for index, item in enumerate(candidates)
    ]


def _normalize_facts(raw_facts: tuple[dict[str, Any], ...], scope: dict[str, Any], precedence: Any) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_facts:
        subject_type = str(raw.get("subject_type", raw.get("subject", "RUNTIME")))
        subject_id = str(raw.get("subject_id", raw.get("subject_ref", scope["project_id"])))
        attribute = str(raw.get("attribute", raw.get("name", ""))).strip()
        if not attribute:
            raise R2_1Error("INVALID_FACT", "fact attribute is required")
        fact_key = str(raw.get("fact_id") or f"{subject_type}:{subject_id}:{attribute}")
        status = normalize_status(raw.get("status"), FACT_STATUSES, FACT_KNOWN)
        value = _value(raw)
        refs = _source_refs(raw)
        if not refs:
            status = FACT_UNKNOWN
        if status == FACT_KNOWN and value is None:
            status = FACT_UNKNOWN
        groups.setdefault(fact_key, []).append(
            {
                "fact_id": fact_key,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "attribute": attribute,
                "value_or_reference": value,
                "status": status,
                "source_refs": refs,
                "valid_until": raw.get("valid_until"),
                "observed_at": raw.get("observed_at"),
            }
        )

    normalized: list[dict[str, Any]] = []
    for fact_key, candidates in groups.items():
        values = {canonical_json(item["value_or_reference"]) for item in candidates}
        chosen = candidates[0]
        status = chosen["status"]
        reason = None
        if any(item["status"] == FACT_CONFLICT for item in candidates):
            status = FACT_CONFLICT
            chosen = {**chosen, "value_or_reference": None}
            reason = "SOURCE_CONFLICT"
        elif len(candidates) > 1 and len({ref for item in candidates for ref in item["source_refs"]}) > 1:
            ranked = _ranked_candidates(candidates, precedence, fact_key)
            if any(item[0] is None for item in ranked):
                status = FACT_CONFLICT
                chosen = {**chosen, "value_or_reference": None}
                reason = "EXPLICIT_PRECEDENCE_REQUIRED"
            else:
                best_rank = min(item[0] for item in ranked)
                winners = [item for item in ranked if item[0] == best_rank]
                if len(winners) != 1:
                    status = FACT_CONFLICT
                    chosen = {**chosen, "value_or_reference": None}
                    reason = "PRECEDENCE_TIE"
                else:
                    chosen = winners[0][2]
                    status = chosen["status"]
        elif len(values) > 1:
            status = FACT_CONFLICT
            chosen = {**chosen, "value_or_reference": None}
            reason = "EXPLICIT_PRECEDENCE_REQUIRED"
        else:
            statuses = [item["status"] for item in candidates]
            status = next((item for item in statuses if item != FACT_KNOWN), FACT_KNOWN)

        source_refs = _unique([ref for item in candidates for ref in item["source_refs"]])
        output = {
            "fact_id": fact_key,
            "subject_type": chosen["subject_type"],
            "subject_id": chosen["subject_id"],
            "attribute": chosen["attribute"],
            "value_or_reference": chosen["value_or_reference"],
            "status": status,
            "source_refs": source_refs,
            "scope": dict(scope),
        }
        if chosen.get("valid_until") is not None:
            output["valid_until"] = chosen["valid_until"]
        if chosen.get("observed_at") is not None:
            output["observed_at"] = chosen["observed_at"]
        if reason:
            output["reason_code"] = reason
        normalized.append(output)
    return sorted(normalized, key=lambda item: item["fact_id"])


def _normalize_capabilities(raw_capabilities: tuple[dict[str, Any], ...], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fact_by_id = {fact["fact_id"]: fact for fact in facts}
    normalized: list[dict[str, Any]] = []
    for raw in raw_capabilities:
        capability_id = str(raw.get("capability_id", raw.get("id", ""))).strip()
        version = str(raw.get("version", raw.get("capability_version", ""))).strip()
        if not capability_id or not version:
            raise R2_1Error("INVALID_CAPABILITY", "capability_id and version are required")

        source_refs = _source_refs(raw)
        status = normalize_status(raw.get("status"), CAPABILITY_STATUSES, CAPABILITY_BLOCKED)
        reason = str(raw.get("reason_code") or "") or None
        required_fact_ids = [str(item) for item in (raw.get("required_fact_ids") or raw.get("required_facts") or [])]
        missing_facts = [fact_id for fact_id in required_fact_ids if fact_id not in fact_by_id]
        blocked_facts = [fact_id for fact_id in required_fact_ids if fact_id in fact_by_id and fact_by_id[fact_id]["status"] != FACT_KNOWN]

        binding_fields = {
            "configuration": ("configuration_ref", "configuration"),
            "environment": ("environment_ref", "environment"),
            "policy": ("policy_ref", "policy"),
        }
        missing_bindings = [
            label
            for label, fields in binding_fields.items()
            if not any(raw.get(field) not in (None, "", {}) for field in fields)
        ]

        if raw.get("valid") is False:
            status = CAPABILITY_INVALID
            reason = reason or "CAPABILITY_INVALID"
        elif raw.get("blocked") is True or raw.get("authorized") is False:
            status = CAPABILITY_BLOCKED
            reason = reason or "CAPABILITY_BLOCKED"
        elif raw.get("available") is False:
            status = CAPABILITY_UNAVAILABLE
            reason = reason or "CAPABILITY_UNAVAILABLE"
        elif raw.get("available") is True:
            status = CAPABILITY_AVAILABLE
        elif status == CAPABILITY_AVAILABLE and missing_bindings:
            status = CAPABILITY_BLOCKED
            reason = reason or "CAPABILITY_BINDING_INCOMPLETE"
        elif status == CAPABILITY_AVAILABLE and (missing_facts or blocked_facts):
            status = CAPABILITY_BLOCKED
            reason = reason or "REQUIRED_FACT_NOT_KNOWN"
        elif missing_facts or blocked_facts:
            status = CAPABILITY_BLOCKED
            reason = reason or "REQUIRED_FACT_NOT_KNOWN"
        elif status == CAPABILITY_AVAILABLE and not source_refs:
            inherited_refs = [ref for fact_id in required_fact_ids for ref in fact_by_id.get(fact_id, {}).get("source_refs", [])]
            source_refs = _unique(inherited_refs)
            if not source_refs:
                status = CAPABILITY_BLOCKED
                reason = reason or "CAPABILITY_PROVENANCE_MISSING"

        if status == CAPABILITY_AVAILABLE and missing_bindings:
            status = CAPABILITY_BLOCKED
            reason = reason or "CAPABILITY_BINDING_INCOMPLETE"

        output = {
            "capability_id": capability_id,
            "version": version,
            "status": status,
            "source_refs": source_refs,
            "required_fact_ids": required_fact_ids,
        }
        for field in ("configuration_ref", "environment_ref", "policy_ref", "configuration", "environment", "policy"):
            if field in raw:
                output[field] = raw[field]
        if reason:
            output["reason_code"] = reason
        normalized.append(output)
    return sorted(normalized, key=lambda item: (item["capability_id"], item["version"]))


class ObservationSnapshotStore:
    """Adapter over the existing truth_snapshots table; never an Event Store."""

    def _resolution_rows(self) -> list[dict[str, Any]]:
        return all_rows(
            "SELECT * FROM truth_snapshots WHERE kind=? ORDER BY observed_at ASC, rowid ASC",
            (SNAPSHOT_KIND,),
        )

    @staticmethod
    def _resolution_from_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            payload = jload(row.get("payload_json"), {})
        except (TypeError, ValueError):
            return None
        resolution = payload.get("resolution") if isinstance(payload, Mapping) else None
        if not isinstance(resolution, Mapping):
            return None
        result = dict(resolution)
        result["snapshot_id"] = row.get("snapshot_id")
        result["snapshot_status"] = row.get("status")
        return result

    def find_by_resolution(self, resolution_id_or_project: str, resolution_id: str | None = None) -> dict[str, Any] | None:
        """Find by global resolution identity; project_id is not an idempotency partition."""
        lookup_id = resolution_id if resolution_id is not None else resolution_id_or_project
        for row in reversed(self._resolution_rows()):
            resolution = self._resolution_from_row(row)
            if resolution and resolution.get("resolution_id") == lookup_id:
                return resolution
        return None

    def save(self, resolution: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(resolution["scope"]["project_id"])
        resolution_id = str(resolution["resolution_id"])
        existing = self.find_by_resolution(resolution_id)
        if existing:
            if existing.get("request_digest") != resolution.get("request_digest"):
                raise IdempotencyConflict(resolution_id)
            return existing

        payload_resolution = dict(resolution)
        payload_resolution["snapshot_id"] = None
        record = truth.add_snapshot(
            project_id,
            SNAPSHOT_KIND,
            f"r2.1://resolution/{resolution_id}",
            {"contract_version": CONTRACT_VERSION, "resolution": payload_resolution},
            valid_until=resolution.get("valid_until"),
        )
        return {**dict(resolution), "snapshot_id": record["snapshot_id"]}

    def read(self, snapshot_id: str) -> dict[str, Any]:
        row = one("SELECT * FROM truth_snapshots WHERE snapshot_id=?", (snapshot_id,))
        if not row:
            raise KeyError(snapshot_id)
        resolution = self._resolution_from_row(row)
        if resolution is None:
            raise R2_1Error("SNAPSHOT_INVALID", f"snapshot is not an R2.1 resolution: {snapshot_id}")
        return resolution


class RuntimeFactsResolver:
    def __init__(self, snapshot_store: ObservationSnapshotStore | None = None):
        self.snapshot_store = snapshot_store or ObservationSnapshotStore()

    def resolve(
        self,
        request: Mapping[str, Any] | ResolutionRequest,
        *,
        facts: list[dict[str, Any]] | None = None,
        capabilities: list[dict[str, Any]] | None = None,
        source_precedence: Any = None,
    ) -> dict[str, Any]:
        raw_request = dict(request) if isinstance(request, Mapping) else request
        validate_secret_boundary(raw_request)
        normalized_request = ResolutionRequest.from_mapping(raw_request)
        if facts is not None:
            normalized_request = ResolutionRequest(
                **{**normalized_request.__dict__, "facts": tuple(dict(item) for item in facts)}
            )
        if capabilities is not None:
            normalized_request = ResolutionRequest(
                **{**normalized_request.__dict__, "capabilities": tuple(dict(item) for item in capabilities)}
            )
        if source_precedence is not None:
            normalized_request = ResolutionRequest(
                **{**normalized_request.__dict__, "source_precedence": source_precedence}
            )
        validate_secret_boundary(normalized_request.declared_mapping())

        request_digest = normalized_request.request_digest or sha256_digest(normalized_request.declared_mapping())
        existing = None
        project_id = str(normalized_request.scope.get("project_id") or "")
        if project_id and normalized_request.resolution_id:
            existing = self.snapshot_store.find_by_resolution(normalized_request.resolution_id)
        if existing:
            if existing.get("request_digest") != request_digest:
                raise IdempotencyConflict(normalized_request.resolution_id)
            return existing

        try:
            scope = _scope(normalized_request)
            facts_result = _normalize_facts(normalized_request.facts, scope, normalized_request.source_precedence)
            capabilities_result = _normalize_capabilities(normalized_request.capabilities, facts_result)
        except R2_1Error as exc:
            return self._invalid(normalized_request, request_digest, exc.code)

        fact_statuses = [fact["status"] for fact in facts_result]
        capability_statuses = [capability["status"] for capability in capabilities_result]
        if CAPABILITY_INVALID in capability_statuses:
            status = RESOLUTION_INVALID
            reason = "CAPABILITY_INVALID"
        elif not facts_result and not capabilities_result:
            status = RESOLUTION_BLOCKED
            reason = "NO_DECLARED_FACTS_OR_CAPABILITIES"
        elif CAPABILITY_BLOCKED in capability_statuses or any(item in _BLOCKING_FACT_STATUSES for item in fact_statuses):
            status = RESOLUTION_BLOCKED
            reason = "REQUIRED_FACT_OR_CAPABILITY_BLOCKED"
        elif CAPABILITY_UNAVAILABLE in capability_statuses:
            status = RESOLUTION_UNAVAILABLE
            reason = "CAPABILITY_UNAVAILABLE"
        else:
            status = RESOLUTION_RESOLVED
            reason = "RESOLUTION_COMPLETE"

        source_refs = _unique(
            [ref for fact in facts_result for ref in fact.get("source_refs", [])]
            + [ref for capability in capabilities_result for ref in capability.get("source_refs", [])]
        )
        fact_set_digest = sha256_digest(
            {
                "scope": scope,
                "facts": facts_result,
                "capabilities": capabilities_result,
            }
        )
        resolution = {
            "contract_version": CONTRACT_VERSION,
            "resolution_id": normalized_request.resolution_id,
            "request_digest": request_digest,
            "snapshot_id": None,
            "fact_set_digest": fact_set_digest,
            "scope": scope,
            "context_refs": dict(normalized_request.context_refs),
            "status": status,
            "facts": facts_result,
            "capabilities": capabilities_result,
            "source_refs": source_refs,
            "reason_code": reason,
            "observed_at": now_iso(),
            "valid_until": normalized_request.valid_until,
        }
        return self.snapshot_store.save(resolution)

    @staticmethod
    def _invalid(request: ResolutionRequest, request_digest: str, reason: str) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "resolution_id": request.resolution_id,
            "request_digest": request_digest,
            "snapshot_id": None,
            "fact_set_digest": None,
            "scope": dict(request.scope),
            "context_refs": dict(request.context_refs),
            "status": RESOLUTION_INVALID,
            "facts": [],
            "capabilities": [],
            "source_refs": [],
            "reason_code": reason,
            "observed_at": now_iso(),
            "valid_until": request.valid_until,
        }


def resolve_runtime_facts(
    request: Mapping[str, Any] | ResolutionRequest,
    *,
    facts: list[dict[str, Any]] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    source_precedence: Any = None,
    snapshot_store: ObservationSnapshotStore | None = None,
) -> dict[str, Any]:
    return RuntimeFactsResolver(snapshot_store).resolve(
        request,
        facts=facts,
        capabilities=capabilities,
        source_precedence=source_precedence,
    )


def read_observation_snapshot(snapshot_id: str, *, snapshot_store: ObservationSnapshotStore | None = None) -> dict[str, Any]:
    return (snapshot_store or ObservationSnapshotStore()).read(snapshot_id)
