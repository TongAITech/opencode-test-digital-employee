from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256

from .contracts import EvidenceInput, EvidenceRecord, _mapping, _optional_text, _safe_value, _text


class EvidenceAttachmentFailure(RuntimeError):
    def __init__(self, message: str = "evidence could not be attached") -> None:
        super().__init__("EVIDENCE_ATTACHMENT_FAILED", message)


def evidence_digest(value: Any) -> str:
    """Return a digest without retaining the evidence payload in Runtime state."""
    try:
        return canonical_sha256(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceAttachmentFailure("evidence content is not canonical JSON") from exc


def build_evidence(
    *,
    evidence_id: str,
    tool_execution_id: str,
    execution_fact_id: str,
    evidence_type: str,
    content: Any | None = None,
    content_digest: str | None = None,
    artifact_reference: str | None = None,
    provenance: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    verification_method: str = "SHA-256",
    verified: bool = True,
) -> EvidenceInput:
    if content_digest is None:
        if content is None:
            raise EvidenceAttachmentFailure("evidence requires content or content_digest")
        try:
            content_digest = evidence_digest(_safe_value(content, "content"))
        except RuntimeError as exc:
            if exc.code == "TOOL_EXECUTION_SENSITIVE_DATA":
                raise EvidenceAttachmentFailure("evidence contains prohibited sensitive data") from exc
            raise
    try:
        return EvidenceInput(
            evidence_id=_text(evidence_id, "evidence_id"),
            tool_execution_id=_text(tool_execution_id, "tool_execution_id"),
            execution_fact_id=_text(execution_fact_id, "execution_fact_id"),
            evidence_type=_text(evidence_type, "evidence_type"),
            content_digest=content_digest,
            artifact_reference=_optional_text(artifact_reference, "artifact_reference"),
            provenance=_mapping(provenance, "provenance"),
            metadata=_mapping(metadata or {}, "metadata"),
            verification_method=_text(verification_method, "verification_method"),
            verified=verified,
        )
    except RuntimeError as exc:
        if exc.code == "TOOL_EXECUTION_SENSITIVE_DATA":
            raise EvidenceAttachmentFailure("evidence contains prohibited sensitive data") from exc
        raise


class EvidenceBuilder:
    def build(self, **kwargs: Any) -> EvidenceInput:
        return build_evidence(**kwargs)


def attach_evidence(*args: Any, **kwargs: Any) -> EvidenceInput:
    return build_evidence(*args, **kwargs)


__all__ = ["EvidenceAttachmentFailure", "EvidenceBuilder", "attach_evidence", "build_evidence", "evidence_digest"]
