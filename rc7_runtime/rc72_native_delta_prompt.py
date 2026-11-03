"""C10 native DSH prompt hydration of an OBSERVED N8 RetryDelta.

Unlike a reference-only ContextEnvelope receipt this transform actually edits
the final native DSH command. It is narrowly scoped: the exact WorkItem and
Mission of the JSON Context, one signed assignment, one R1 child-parent binding,
and an OBSERVED retry context must match. It changes ONLY the task-scoped
input_refs field, leaving parent TestObligation, source mapping, oracle,
RequiredShape and native instructions byte-for-byte semantically identical.

If the evidence is absent, malformed, or not provably smaller, this optional
optimization returns the original prompt unchanged; it never stops mandatory
test execution for economy reasons. All omitted lineage remains in R1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from .rc72_lossless_prompt_compaction import _parse_object, _strict_pairs, _reject_nonfinite


@dataclass(frozen=True)
class NativeRetryPrompt:
    prompt: str
    status: str
    input_refs_before: Tuple[str, ...] = ()
    input_refs_after: Tuple[str, ...] = ()
    removed_refs: Tuple[str, ...] = ()
    bytes_saved: int = 0

    @property
    def applied(self) -> bool:
        return self.status == "NATIVE_RETRY_DELTA_APPLIED"


def hydrate_native_retry_delta(prompt: str, metadata: Mapping[str, Any]) -> NativeRetryPrompt:
    if not isinstance(prompt, str):
        raise TypeError("RC72_NATIVE_RETRY_PROMPT_REQUIRED")
    unchanged = NativeRetryPrompt(prompt=prompt, status="UNCHANGED")
    if not isinstance(metadata, Mapping):
        raise TypeError("RC72_NATIVE_RETRY_METADATA_REQUIRED")
    if (
        metadata.get("context_mode") != "RETRY_DELTA"
        or metadata.get("retry_context_observation_status") != "OBSERVED"
        or metadata.get("retry_delta_native_authorized") is not True
        or metadata.get("context_projection_status") != "REFERENCE_ONLY"
        or metadata.get("role") in {
            "requirement_review", "source_review", "code_review",
            "design_review", "data_verify",
        }
    ):
        return unchanged

    parent = metadata.get("parent_attempt_id")
    assignment_id = metadata.get("attempt_id")
    mission_id = metadata.get("mission_id")
    workitem_id = metadata.get("workitem_id")
    if any(not isinstance(item, str) or not item for item in
           (parent, assignment_id, mission_id, workitem_id)):
        return unchanged
    old_allowed = metadata.get("context_canonical_input_refs")
    new_refs = metadata.get("context_effective_refs")
    if (
        not isinstance(old_allowed, (tuple, list))
        or not isinstance(new_refs, (tuple, list))
        or not new_refs
        or any(not isinstance(x, str) or not x for x in (*old_allowed, *new_refs))
        or len(set(new_refs)) != len(new_refs)
    ):
        return unchanged
    # Must contain a real parent Attempt summary and at least one real Gap
    # or changed Evidence locator: never replace context with an empty delta.
    if not isinstance(metadata.get("retry_previous_summary_ref"), str):
        return unchanged
    if metadata["retry_previous_summary_ref"] not in new_refs:
        return unchanged

    marker = "Context="
    offset = prompt.rfind(marker)
    if offset < 0 or not prompt[:offset].endswith((" ", "\n")):
        return unchanged
    prefix = prompt[:offset + len(marker)]
    suffix = prompt[offset + len(marker):]
    decoder = json.JSONDecoder(
        object_pairs_hook=_strict_pairs, parse_constant=_reject_nonfinite
    )
    try:
        context, trailing = _parse_object(suffix, decoder)
        shape = None
        if trailing:
            if not trailing.startswith(" RequiredShape="):
                return unchanged
            shape, residue = _parse_object(trailing[len(" RequiredShape="):], decoder)
            if residue:
                return unchanged
        if (
            context.get("mission_id") != mission_id
            or context.get("workitem_id") != workitem_id
        ):
            return unchanged
        native_refs = context.get("input_refs")
        if (
            not isinstance(native_refs, list)
            or any(not isinstance(ref, str) or not ref for ref in native_refs)
            or len(set(native_refs)) != len(native_refs)
            or not set(native_refs).issubset(set(old_allowed))
        ):
            return unchanged
        effective = list(new_refs)
        if native_refs == effective:
            return unchanged
        compact = dict(context)
        compact["input_refs"] = effective
        # The prompt's other contract fields, including source/Oracle/Case,
        # are unmodified. JSON serialization is deterministic.
        new_json = json.dumps(compact, sort_keys=True, ensure_ascii=False)
        candidate = prefix + new_json
        if shape is not None:
            candidate += " RequiredShape=" + json.dumps(
                shape, sort_keys=True, ensure_ascii=False
            )
        old_bytes = len(prompt.encode("utf-8"))
        new_bytes = len(candidate.encode("utf-8"))
    except (ValueError, UnicodeError, OverflowError, TypeError, RecursionError):
        return unchanged
    # Context economy must not create extra prompt growth or secretly claim
    # a semantic improvement merely because a batch has fewer refs.
    if new_bytes >= old_bytes:
        return unchanged
    return NativeRetryPrompt(
        prompt=candidate,
        status="NATIVE_RETRY_DELTA_APPLIED",
        input_refs_before=tuple(native_refs),
        input_refs_after=tuple(effective),
        removed_refs=tuple(ref for ref in native_refs if ref not in effective),
        bytes_saved=old_bytes - new_bytes,
    )
