"""RC7.2 lossless DSH token-usage wiring.

The RC6 DSH launcher intentionally keeps its stable ``execute`` return contract:
``(WorkerInvocation, output)``.  It already persists the complete DSH stdout
JSONL as a canonical ``file://`` evidence reference before returning.

This adapter preserves that launcher contract and replays only the persisted JSON
objects into ``TokenUsageAuditService``.  It never invents provider/model/token
values and it records UNKNOWN only when a real model-response signal is present
but DSH did not expose token counters.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

from .rc72_model_usage import TokenUsageAuditService


class Rc72TokenUsageWiringError(RuntimeError):
    pass


class Rc72TokenUsageLauncherProxy:
    """Observe persisted DSH JSONL without changing the wrapped launcher API."""

    _MODEL_RESPONSE_KINDS = {
        "assistant",
        "final",
        "message",
        "response",
        "completion",
        "text",
    }

    def __init__(self, launcher: Any, audit: TokenUsageAuditService) -> None:
        if launcher is None:
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_LAUNCHER_REQUIRED")
        if audit is None:
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_AUDIT_REQUIRED")
        self._launcher = launcher
        self.audit = audit

    def __getattr__(self, name: str) -> Any:
        return getattr(self._launcher, name)

    def execute(self, assignment: Any, prompt: str) -> Tuple[Any, Dict[str, Any]]:
        result = self._launcher.execute(assignment, prompt)
        if not isinstance(result, tuple) or len(result) != 2:
            raise Rc72TokenUsageWiringError("RC72_DSH_EXECUTE_CONTRACT_INVALID")
        invocation, output = result
        raw_output_ref = self._raw_output_ref(invocation)
        events = self._read_events(raw_output_ref)
        if self._has_model_call_signal(events):
            self.audit.observe(
                mission_id=self._required_invocation_id(invocation, "mission_id"),
                attempt_id=self._required_invocation_id(invocation, "attempt_id"),
                assignment_id=self._required_invocation_id(invocation, "assignment_id"),
                raw_output_ref=raw_output_ref,
                events=events,
                dsh_session_id=self._required_invocation_id(invocation, "dsh_session_id"),
            )
        return invocation, output

    @staticmethod
    def _required_invocation_id(invocation: Any, name: str) -> str:
        value = getattr(invocation, name, None)
        if not isinstance(value, str) or not value.strip():
            raise Rc72TokenUsageWiringError(
                "RC72_TOKEN_USAGE_%s_REQUIRED" % name.upper()
            )
        return value.strip()

    @classmethod
    def _raw_output_ref(cls, invocation: Any) -> str:
        refs = getattr(invocation, "evidence_refs", None)
        if not isinstance(refs, (list, tuple)):
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_EVIDENCE_REFS_REQUIRED")
        raw_output_ref = next(
            (
                ref
                for ref in refs
                if isinstance(ref, str) and ref.startswith("file://")
            ),
            "",
        )
        if not raw_output_ref:
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_RAW_OUTPUT_REF_MISSING")
        return raw_output_ref

    @staticmethod
    def _read_events(raw_output_ref: str) -> Tuple[Dict[str, Any], ...]:
        raw_path = raw_output_ref[len("file://") :]
        if not raw_path:
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_RAW_OUTPUT_PATH_MISSING")
        path = Path(raw_path)
        if not path.is_file():
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_RAW_OUTPUT_NOT_FOUND")
        events = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise Rc72TokenUsageWiringError("RC72_TOKEN_USAGE_RAW_OUTPUT_UNREADABLE") from exc
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return tuple(events)

    @classmethod
    def _has_model_call_signal(cls, events: Sequence[Dict[str, Any]]) -> bool:
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = str(
                event.get("type")
                or event.get("event")
                or event.get("kind")
                or ""
            ).strip().lower()
            if kind in cls._MODEL_RESPONSE_KINDS:
                return True
            if kind in {"usage", "token_usage", "model_usage"}:
                return True
            if "final" in kind or "assistant" in kind or "completion" in kind:
                return True
            if cls._contains_usage_mapping(event):
                return True
        return False

    @classmethod
    def _contains_usage_mapping(cls, value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"usage", "token_usage", "model_usage"} and isinstance(child, dict):
                    return True
                if cls._contains_usage_mapping(child):
                    return True
        elif isinstance(value, list):
            return any(cls._contains_usage_mapping(child) for child in value)
        return False
