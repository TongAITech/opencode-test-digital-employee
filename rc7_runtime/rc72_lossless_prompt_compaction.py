"""C10 lossless native prompt JSON serialization at the actual DSH command boundary.

Only compact a terminal Context=<JSON object> [RequiredShape=<JSON object>]
produced by the frozen N1-N5 prompt authors. Reject ambiguous/malformed data,
duplicate keys and trailing prose. Objects, strings and array order remain
identical. This is a measured *byte* reduction, never a measured token saving.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class NativePromptCompaction:
    prompt: str
    status: str
    original_bytes: int
    compacted_bytes: int

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.compacted_bytes


def _strict_pairs(pairs: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("NONFINITE_JSON")


def _parse_object(text: str, decoder: json.JSONDecoder) -> Tuple[Dict[str, Any], str]:
    start = len(text) - len(text.lstrip())
    obj, end = decoder.raw_decode(text, start)
    if not isinstance(obj, dict):
        raise ValueError("CONTEXT_OBJECT_REQUIRED")
    return obj, text[end:]


def compact_native_prompt_json(prompt: str) -> NativePromptCompaction:
    """Return an unchanged prompt unless JSON equivalence can be proven.

    This intentionally makes NO claims about provider tokenization or reduction
    in semantic input context. A valid prompt may still be left untouched.
    """
    if not isinstance(prompt, str):
        raise TypeError("NATIVE_PROMPT_REQUIRED")
    original_bytes = len(prompt.encode("utf-8"))
    unchanged = NativePromptCompaction(
        prompt=prompt, status="UNCHANGED",
        original_bytes=original_bytes, compacted_bytes=original_bytes,
    )
    marker = "Context="
    index = prompt.rfind(marker)
    if index < 0:
        return unchanged
    # N1-N5 frozen prompt authors append the JSON at the end. Never alter a
    # casual occurrence of "Context=" in natural-language instructions.
    original_prefix = prompt[:index]
    if not original_prefix.endswith((" ", "\n")):
        return unchanged
    after_marker = prompt[index + len(marker):]
    decoder = json.JSONDecoder(
        object_pairs_hook=_strict_pairs, parse_constant=_reject_nonfinite,
    )
    try:
        context, remaining = _parse_object(after_marker, decoder)
        compact_context = json.dumps(
            context, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False,
        )
        if remaining == "":
            candidate = original_prefix + marker + compact_context
        elif remaining.startswith(" RequiredShape="):
            shape, trailing = _parse_object(
                remaining[len(" RequiredShape="):], decoder,
            )
            if trailing:
                return unchanged
            compact_shape = json.dumps(
                shape, ensure_ascii=False, separators=(",", ":"),
                allow_nan=False,
            )
            candidate = (
                original_prefix + marker + compact_context
                + " RequiredShape=" + compact_shape
            )
        else:
            return unchanged
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        return unchanged

    try:
        compacted_bytes = len(candidate.encode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        # Original ASCII-escaped surrogate data may be legitimate input for a
        # native caller; never let an optional optimizer break the worker.
        return unchanged
    if compacted_bytes >= original_bytes:
        return unchanged
    return NativePromptCompaction(
        prompt=candidate, status="LOSSLESS_JSON",
        original_bytes=original_bytes, compacted_bytes=compacted_bytes,
    )
