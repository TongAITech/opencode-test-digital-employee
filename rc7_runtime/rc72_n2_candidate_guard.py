"""RC7.2 hardened N2 Requirement handoff + immediate raw-evidence anchor.

The base N2 DSH handoff proves that a fresh worker/session/tool execution
occurred.  This module is the only promotion-eligible entry point: it extends
the candidate contract with explicit trace_links and immediately anchors the
exact raw JSONL bytes in R1.  Downstream canonical Requirement promotion must
require this anchor and re-hash the raw bytes before trusting the candidate.

The anchor is execution/evidence integrity truth only.  It never accepts the
Requirement analysis, never emits a NodeDelivery/NodeGate, and never claims
Q7/field/BANK_FINAL status.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_n2_requirement_handoff import (
    N2RequirementDshHandoffService,
    N2RequirementHandoffError,
    install_rc72_n2_requirement_handoff_overlay,
)
from .truth_overlay import install_rc7_truth_overlay


_ANCHOR_ARTIFACT = "rc72_n2_dsh_evidence_anchor"
_ANCHOR_EVENT = "RC72_N2_DSH_EVIDENCE_ANCHOR_UPSERTED"
_ANCHOR_BUCKET = "rc72_n2_dsh_evidence_anchors"
_CANDIDATE_SCHEMA = "RC72_N2_REQUIREMENT_CANDIDATE_V1_TRACEABLE"


class N2RequirementCandidateGuardError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2RequirementCandidateGuardError(
            "RC72_N2_GUARD_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_rc72_n2_dsh_evidence_anchor(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "anchor_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "requirement_id", "attempt_id", "assignment_id",
        "dispatch_id", "mission_node_id", "workitem_id", "worker_instance_id",
        "dsh_session_id", "candidate_output_ref", "raw_output_ref",
        "raw_output_sha256", "candidate_schema",
    ):
        out[name] = _contracts._require_str(out, name)
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_DSH_SESSION_INVALID"
        )
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_RAW_OUTPUT_REF_INVALID"
        )
    if (
        not out["raw_output_sha256"].startswith("sha256:")
        or len(out["raw_output_sha256"]) != 71
    ):
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_RAW_OUTPUT_SHA256_INVALID"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_CANDIDATE_SCHEMA_INVALID"
        )
    value = out.get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_CREATED_AT_INVALID"
        )
    for forbidden in (
        "analysis", "node_delivery_id", "node_gate", "node_gate_id",
        "node_pass", "evaluation", "evaluation_result", "q7_pass",
        "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N2_GUARD_BUSINESS_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N2_GUARD_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ANCHOR_ARTIFACT
    return out


def install_rc72_n2_candidate_guard_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_n2_requirement_handoff_overlay()
    _contracts.VALIDATORS[_ANCHOR_ARTIFACT] = validate_rc72_n2_dsh_evidence_anchor
    _truth.BUCKETS[_ANCHOR_ARTIFACT] = _ANCHOR_BUCKET
    _truth.IDENTITY_FIELDS[_ANCHOR_ARTIFACT] = "anchor_id"
    _truth.EVENT_TYPES[_ANCHOR_EVENT] = (_ANCHOR_ARTIFACT, "anchor_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _ANCHOR_BUCKET):
        setattr(projection, _ANCHOR_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ANCHOR_ARTIFACT, {})


class N2TraceableRequirementDshHandoffService(N2RequirementDshHandoffService):
    """N2 DSH handoff with reviewer-compatible traceability syntax."""

    @staticmethod
    def _validate_candidate(
        candidate: Mapping[str, Any], requirement_id: str
    ) -> Dict[str, Any]:
        normalized = N2RequirementDshHandoffService._validate_candidate(
            candidate, requirement_id
        )
        facts = normalized["facts"]
        source_refs = list(facts["source_refs"])
        for ref in source_refs:
            if "://" not in ref:
                raise N2RequirementHandoffError(
                    "RC72_N2_HANDOFF_CANDIDATE_SOURCE_REF_NOT_LOCATOR"
                )

        analysis = facts["analysis"]
        trace_links = analysis.get("trace_links")
        if not isinstance(trace_links, list):
            raise N2RequirementHandoffError(
                "RC72_N2_HANDOFF_TRACE_LINKS_REQUIRED"
            )
        for index, link in enumerate(trace_links):
            if not isinstance(link, Mapping):
                raise N2RequirementHandoffError(
                    "RC72_N2_HANDOFF_TRACE_LINK_INVALID:%d" % index
                )
            source_id = link.get("source_id")
            atomic_id = link.get("atomic_id")
            evidence_ref = link.get("evidence_ref")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (source_id, atomic_id, evidence_ref)
            ):
                raise N2RequirementHandoffError(
                    "RC72_N2_HANDOFF_TRACE_LINK_FIELDS_REQUIRED:%d" % index
                )
            if evidence_ref not in source_refs:
                raise N2RequirementHandoffError(
                    "RC72_N2_HANDOFF_TRACE_EVIDENCE_NOT_SOURCE_REF:%d" % index
                )

        for name in ("source_assertions", "atomic_statements"):
            values = analysis.get(name)
            if not isinstance(values, list):
                raise N2RequirementHandoffError(
                    "RC72_N2_HANDOFF_ANALYSIS_DIMENSION_INVALID:%s" % name
                )
            for index, item in enumerate(values):
                if not isinstance(item, Mapping):
                    raise N2RequirementHandoffError(
                        "RC72_N2_HANDOFF_ANALYSIS_ITEM_INVALID:%s:%d"
                        % (name, index)
                    )
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id.strip():
                    raise N2RequirementHandoffError(
                        "RC72_N2_HANDOFF_ANALYSIS_ITEM_ID_REQUIRED:%s:%d"
                        % (name, index)
                    )
        return normalized

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        base = super()._prompt(assignment)
        extension = {
            "analysis.trace_links": [
                {
                    "source_id": "id from analysis.source_assertions",
                    "atomic_id": "id from analysis.atomic_statements",
                    "evidence_ref": "exact locator from facts.source_refs",
                }
            ],
            "atomic_statement_contract": {
                "id": "stable id",
                "source_ref": "real source locator",
                "testable": "boolean; false is allowed but will fail sufficiency",
            },
            "rule": (
                "analysis.trace_links is an additional required key in the nested "
                "analysis object. Never invent evidence aliases: evidence_ref must "
                "be one exact facts.source_refs locator. Empty trace_links remains "
                "a candidate but will fail independent sufficiency when facts exist."
            ),
        }
        return (
            base
            + "\nRC72_N2_TRACEABILITY_EXTENSION="
            + json.dumps(extension, ensure_ascii=False, sort_keys=True)
        )


class N2RequirementEvidenceAnchorService:
    """Hash-anchor one traceable N2 raw DSH handoff before any promotion."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n2_candidate_guard_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()

    @staticmethod
    def _anchor_id(attempt_id: str) -> str:
        return _stable_id("N2ANCH", attempt_id, "DSH_RAW_OUTPUT")

    def _attempt(
        self, release_batch_id: str, requirement_id: str
    ) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n2_requirement_attempt", release_batch_id=release_batch_id
        )
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
            and row.get("state") == "WORKER_COMPLETED_PENDING_DELIVERY"
            and row.get("handoff_status") == "DSH_SESSION_OBSERVED"
            and row.get("process_outcome") == "SUCCEEDED"
        ]
        if len(exact) != 1:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_EXACT_ATTEMPT_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    def _raw_candidate(
        self, attempt: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], str, str, Tuple[Dict[str, Any], ...]]:
        file_refs = [
            ref for ref in list(attempt.get("runtime_evidence_refs") or [])
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(file_refs) != 1:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_DSH_EVIDENCE_REQUIRED:%d" % len(file_refs)
            )
        content_ref = file_refs[0]
        path = Path(content_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_EVIDENCE_NOT_FOUND"
            )
        raw = path.read_bytes()
        if not raw:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_EVIDENCE_EMPTY"
            )
        raw_hash = _sha256(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_EVIDENCE_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_RAW_EVENTS_REQUIRED"
            )
        session_id = DshHeadlessWorkerLauncher._session_id(events)
        if session_id != attempt.get("dsh_session_id"):
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_DSH_SESSION_MISMATCH"
            )
        parsed_calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
        observed_calls = tuple(
            {
                "call_ref": str(item.get("call_ref") or ""),
                "tool_name": str(item.get("tool_name") or ""),
            }
            for item in list(attempt.get("observed_tool_calls") or [])
        )
        if parsed_calls != observed_calls:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_TOOL_CALL_EVIDENCE_MISMATCH"
            )
        candidate = DshHeadlessWorkerLauncher._final_json(events)
        try:
            normalized = N2TraceableRequirementDshHandoffService._validate_candidate(
                candidate, str(attempt["requirement_id"])
            )
        except N2RequirementHandoffError as exc:
            raise N2RequirementCandidateGuardError(str(exc)) from exc
        return normalized, content_ref, raw_hash, parsed_calls

    def anchor(
        self, *, release_batch_id: str, requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        attempt = self._attempt(release_batch_id, requirement_id)
        _candidate, content_ref, raw_hash, _calls = self._raw_candidate(attempt)
        anchor_id = self._anchor_id(str(attempt["attempt_id"]))
        expected = {
            "release_id": attempt.get("release_id"),
            "mission_id": attempt.get("mission_id"),
            "release_batch_id": attempt.get("release_batch_id"),
            "source_commit": self.source_commit,
            "requirement_id": requirement_id,
            "attempt_id": attempt.get("attempt_id"),
            "assignment_id": attempt.get("assignment_id"),
            "dispatch_id": attempt.get("dispatch_id"),
            "mission_node_id": attempt.get("mission_node_id"),
            "workitem_id": attempt.get("workitem_id"),
            "worker_instance_id": attempt.get("worker_instance_id"),
            "dsh_session_id": attempt.get("dsh_session_id"),
            "candidate_output_ref": attempt.get("candidate_output_ref"),
            "raw_output_ref": content_ref,
            "raw_output_sha256": raw_hash,
            "candidate_schema": _CANDIDATE_SCHEMA,
        }
        existing = self.truth.query(_ANCHOR_ARTIFACT, anchor_id=anchor_id)
        if existing:
            if len(existing) != 1:
                raise N2RequirementCandidateGuardError(
                    "RC72_N2_GUARD_ANCHOR_NOT_UNIQUE"
                )
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N2RequirementCandidateGuardError(
                        "RC72_N2_GUARD_ANCHOR_CONFLICT"
                    )
            return dict(existing[0])
        payload = dict(expected)
        payload.update({
            "anchor_id": anchor_id,
            "created_at": int(
                attempt.get("updated_at") or attempt.get("created_at") or 0
            ),
            "artifact_version": 1,
        })
        self.truth.append_atomic(_ANCHOR_EVENT, payload)
        rows = self.truth.query(_ANCHOR_ARTIFACT, anchor_id=anchor_id)
        if len(rows) != 1:
            raise N2RequirementCandidateGuardError(
                "RC72_N2_GUARD_ANCHOR_PERSISTENCE_FAILED"
            )
        return rows[0]


class N2GovernedRequirementHandoffService:
    """Preferred N2 handoff: strict traceable DSH Attempt + immediate hash anchor."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        self.handoff_service = N2TraceableRequirementDshHandoffService(
            truth,
            source_commit=source_commit,
            launcher=launcher,
            allowed_tools=allowed_tools,
        )
        self.anchor_service = N2RequirementEvidenceAnchorService(
            truth,
            source_commit=source_commit,
            state_root=str(launcher.state_root),
        )

    def handoff(
        self, *, release_batch_id: str, requirement_id: str
    ) -> Dict[str, Any]:
        result = self.handoff_service.handoff(
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
        )
        anchor = self.anchor_service.anchor(
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
        )
        out = dict(result)
        out.update({
            "evidence_anchor_id": anchor["anchor_id"],
            "raw_output_sha256": anchor["raw_output_sha256"],
            "candidate_schema": anchor["candidate_schema"],
        })
        return out


install_rc72_n2_candidate_guard_overlay()
