"""RC7.2 C10 source-bound context projection for native DSH model calls.

This is a provenance/audit boundary, NOT a replacement prompt author and NOT
proof of token savings.  It never mutates Tasks, canonical artifacts, or DSH
commands.  Native N1-N5 prompts keep their mandatory instructions, source
reads, oracles, reviewer independence and unresolved business gaps.

A retry is delta-eligible only when canonical R1 has an OBSERVED child/parent
retry context for this exact WorkItem/Attempt. Unknown retry context never
causes mandatory upstream context to be silently removed.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_context_economy import (
    ContextAffinity, ContextEnvelopeBuilder, ExecutionMode,
    SemanticWorkDescriptor, build_retry_delta,
)
from .rc72_model_economy import MissionCriticality, SemanticCostClass
from .rc72_retry_context import (
    _ensure_projection_bucket, _retry_delta_digest,
    install_rc72_retry_context_overlay,
)


class NativeContextProjectionError(ContractError):
    pass


def _refs(values: Any, name: str) -> Tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(item, str) or not item.strip() for item in values
    ):
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_%s_INVALID" % name)
    return tuple(dict.fromkeys(value.strip() for value in values))


def native_context_projection(
    truth: TruthRuntime,
    *,
    assignment: Any,
    task: Mapping[str, Any],
    mission_id: str,
    release_id: str,
    execution_mode: str = "SEMANTIC",
    mission_criticality: str = "UNKNOWN",
    semantic_cost_class: str = "UNKNOWN",
) -> Dict[str, Any]:
    """Compile one canonical ContextEnvelope from an existing Task and assignment.

    The projected REF counts are NOT claimable prompt savings until the native
    production prompt is actually built from the projection.
    """
    if task.get("mission_id") != mission_id or task.get("release_id") != release_id:
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_CANONICAL_TASK_SCOPE_MISMATCH")
    if getattr(assignment, "mission_id", None) != mission_id:
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_CANONICAL_ASSIGNMENT_SCOPE_MISMATCH")
    workitem_id = task.get("task_id")
    attempt_id = getattr(assignment, "attempt_id", None)
    if not isinstance(workitem_id, str) or not workitem_id.strip():
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_WORKITEM_REQUIRED")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_ATTEMPT_REQUIRED")

    input_refs = _refs(task.get("input_artifact_refs"), "CANONICAL_INPUT_REFS")
    # Reviewer contexts carry the source candidate content_ref in their own
    # signed assignment; do not omit it just because it was not a producer
    # Task input. No source document bytes are copied into the envelope.
    worker_refs = _refs(getattr(assignment, "input_refs", ()), "WORKER_INPUT_REFS")
    combined_refs = tuple(dict.fromkeys(input_refs + worker_refs))
    gap_refs = _refs(task.get("gap_refs"), "CANONICAL_GAP_REFS")

    install_rc72_retry_context_overlay()
    _ensure_projection_bucket(truth)
    retry_rows = truth.query(
        "rc72_retry_context",
        mission_id=mission_id,
        workitem_id=workitem_id,
        attempt_id=attempt_id,
    )
    if len(retry_rows) > 1:
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_RECEIPT_NOT_UNIQUE")
    lineage_rows = truth.query(
        "rc72_workitem_attempt_binding",
        mission_id=mission_id,
        workitem_id=workitem_id,
        attempt_id=attempt_id,
    )
    if len(lineage_rows) > 1:
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_ATTEMPT_BINDING_NOT_UNIQUE")
    parent_id = (
        str(lineage_rows[0].get("parent_attempt_id") or "").strip()
        if lineage_rows else ""
    )
    retry = None
    mode = "NORMAL"
    retry_observation_status = "NONE"
    retry_native_authorized = False
    previous_summary_ref = None
    retry_gap_refs = ()
    retry_evidence_refs = ()
    retry_dependency_refs = ()
    if retry_rows:
        receipt = retry_rows[0]
        retry_observation_status = str(receipt.get("observation_status") or "UNKNOWN")
        receipt_parent = str(receipt.get("parent_attempt_id") or "").strip()
        if not receipt_parent or (parent_id and receipt_parent != parent_id):
            raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_PARENT_MISMATCH")
        if receipt.get("release_id") != release_id:
            raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_RELEASE_MISMATCH")
        parent_id = receipt_parent
        if receipt.get("observation_status") == "OBSERVED":
            if not set(receipt.get("explicit_gap_refs") or []).issubset(set(gap_refs)):
                raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_GAP_LINEAGE_MISMATCH")
            mode = str(receipt.get("context_mode") or "")
            if mode not in {"RETRY_DELTA", "FULL_CONTEXT_RETRY"}:
                raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_MODE_INVALID")
            retry = build_retry_delta(
                previous_attempt_summary_ref=receipt.get("previous_attempt_summary_ref"),
                explicit_gap_refs=receipt.get("explicit_gap_refs") or (),
                delta_evidence_refs=receipt.get("delta_evidence_refs") or (),
                changed_dependency_refs=receipt.get("changed_dependency_refs") or (),
                full_context_reason=receipt.get("full_context_reason"),
            )
            if receipt.get("retry_delta_sha256") != _retry_delta_digest(retry):
                raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_RETRY_DELTA_DIGEST_MISMATCH")
            previous_summary_ref = retry.previous_attempt_summary_ref
            retry_gap_refs = tuple(retry.explicit_gap_refs)
            retry_evidence_refs = tuple(retry.delta_evidence_refs)
            retry_dependency_refs = tuple(retry.changed_dependency_refs)
            # The source producer alone may swap prompt input_refs. A valid
            # reviewer candidate must never be lost by reducing upstream
            # source refs. Require an actual signed child assignment and
            # resolved R1 parent Attempt lineage before applying.
            binding = lineage_rows[0] if len(lineage_rows) == 1 else {}
            retry_native_authorized = bool(
                mode == "RETRY_DELTA"
                and binding.get("release_id") == release_id
                and binding.get("mission_node_lineage_status") == "RESOLVED"
                and binding.get("parent_attempt_id") == receipt_parent
                and receipt.get("assignment_id")
                    == getattr(assignment, "assignment_id", None)
                and receipt.get("attempt_id") == attempt_id
            )
        else:
            mode = "RETRY_DELTA_UNKNOWN"
    elif parent_id:
        mode = "RETRY_DELTA_UNKNOWN"

    try:
        descriptor = SemanticWorkDescriptor(
            workitem_id=workitem_id,
            mission_id=mission_id,
            node=str(task.get("node") or ""),
            stage=str(task.get("node") or ""),
            execution_mode=ExecutionMode(execution_mode),
            mission_criticality=MissionCriticality(mission_criticality),
            semantic_cost_class=SemanticCostClass(semantic_cost_class),
            affinity=ContextAffinity(),
            input_refs=combined_refs,
            gap_refs=gap_refs,
            retry_delta=retry,
            batch_eligible=False,
        )
        envelope = ContextEnvelopeBuilder.build((descriptor,))
    except (ValueError, TypeError) as exc:
        raise NativeContextProjectionError("RC72_NATIVE_CONTEXT_DESCRIPTOR_INVALID") from exc

    effective = tuple(dict.fromkeys(
        envelope.shared_refs + envelope.workitem_refs[workitem_id]
    ))
    canonical = set(combined_refs) | set(gap_refs)
    return {
        "context_envelope_id": envelope.envelope_id,
        "context_envelope_sha256": envelope.context_sha256,
        "context_mode": mode,
        "context_canonical_ref_count": len(canonical),
        "context_effective_ref_count": len(effective),
        "context_unhydrated_lineage_ref_count": len(canonical - set(effective)),
        "context_projection_applied_to_prompt": False,
        "context_projection_status": "REFERENCE_ONLY",
        "parent_attempt_id": parent_id or None,
        "context_canonical_input_refs": combined_refs,
        "context_effective_refs": effective,
        "retry_context_observation_status": retry_observation_status,
        "retry_delta_native_authorized": retry_native_authorized,
        "retry_previous_summary_ref": previous_summary_ref,
        "retry_explicit_gap_refs": retry_gap_refs,
        "retry_delta_evidence_refs": retry_evidence_refs,
        "retry_changed_dependency_refs": retry_dependency_refs,
    }
