"""Verified reader for evaluator-facing RC7 worker candidate payloads.

Workers never hand Python objects directly to acceptance gates. The DSH bridge
persists a canonical envelope, hashes the exact bytes, and records that file as
an RC7 Artifact. Evaluators use this reader so a modified/missing/non-file
candidate cannot be silently accepted after worker handoff.

RC7.2 also hardens inherited DSH final-JSON extraction.  The legacy parser
returns the *last* decodable JSON object found in text.  That works for flat
payloads, but a governed candidate such as ``{"facts": {...}}`` can therefore
collapse to the innermost nested object.  The compatibility hook below only
intercepts the explicit RC7.2 candidate contract (status/facts/unknowns/gaps),
selects the outer contract object, and otherwise delegates unchanged to the
inherited parser.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime


_RC72_CANDIDATE_KEYS = frozenset(("status", "facts", "unknowns", "gaps"))


def _event_text_values(event: Mapping[str, Any]) -> Iterable[str]:
    """Yield text-bearing fields without inventing a new DSH event schema."""
    for key in ("text", "content", "output", "result"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            yield value
    message = event.get("message")
    if isinstance(message, Mapping):
        for key in ("text", "content", "output"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                yield value


def _rc72_contract_candidate(events: Iterable[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the outer RC7.2 candidate contract, never an inner facts object."""
    decoder = json.JSONDecoder()
    texts = []
    for event in events:
        if isinstance(event, Mapping):
            texts.extend(_event_text_values(event))

    # Prefer later DSH output while, within each text value, preferring the
    # earliest object that satisfies the complete top-level contract.  This is
    # the inverse of the legacy "last nested object wins" behavior.
    for text in reversed(texts):
        stripped = text.strip()
        try:
            exact = json.loads(stripped)
        except (TypeError, ValueError):
            exact = None
        if isinstance(exact, dict) and _RC72_CANDIDATE_KEYS.issubset(exact):
            return dict(exact)

        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _end = decoder.raw_decode(text[index:])
            except ValueError:
                continue
            if isinstance(value, dict) and _RC72_CANDIDATE_KEYS.issubset(value):
                return dict(value)
    return None


def install_rc72_dsh_candidate_contract_parser() -> None:
    """Add an RC7.2 contract-aware front door while preserving legacy fallback."""
    marker = "_rc72_candidate_contract_parser_installed"
    if getattr(DshHeadlessWorkerLauncher, marker, False):
        return

    inherited = DshHeadlessWorkerLauncher._final_json

    def _contract_aware_final_json(events):
        candidate = _rc72_contract_candidate(events)
        if candidate is not None:
            return candidate
        return inherited(events)

    DshHeadlessWorkerLauncher._final_json = staticmethod(_contract_aware_final_json)
    setattr(DshHeadlessWorkerLauncher, marker, True)


# candidate_payload is imported by the RC7 package bootstrap before RC7.2
# completion services run, so every RC7.2 DSH handoff uses the hardened parser.
install_rc72_dsh_candidate_contract_parser()


class CandidatePayloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidatePayload:
    artifact_id: str
    mission_id: str
    producer_task_id: str
    artifact_type: str
    content_ref: str
    content_hash: str
    semantic_payload: Dict[str, Any]
    envelope: Dict[str, Any]


class CandidatePayloadReader:
    def load(
        self,
        truth: TruthRuntime,
        artifact_id: str,
        *,
        expected_mission_id: Optional[str] = None,
        expected_task_id: Optional[str] = None,
    ) -> CandidatePayload:
        rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise CandidatePayloadError("CANDIDATE_ARTIFACT_NOT_UNIQUE")
        row = rows[0]
        mission_id = str(row.get("mission_id") or "")
        producer_task_id = str(row.get("producer_task_id") or "")
        artifact_type = str(row.get("artifact_type_name") or "")
        content_ref = str(row.get("content_ref") or "")
        content_hash = str(row.get("content_hash") or "")

        if expected_mission_id is not None and mission_id != expected_mission_id:
            raise CandidatePayloadError("CANDIDATE_MISSION_MISMATCH")
        if expected_task_id is not None and producer_task_id != expected_task_id:
            raise CandidatePayloadError("CANDIDATE_PRODUCER_TASK_MISMATCH")
        if str(row.get("state") or "").upper() != "VALID":
            raise CandidatePayloadError("CANDIDATE_ARTIFACT_NOT_VALID")
        if not content_ref.startswith("file://"):
            raise CandidatePayloadError("CANDIDATE_CONTENT_MUST_BE_RUNTIME_FILE")
        if not content_hash.startswith("sha256:") or len(content_hash) != len("sha256:") + 64:
            raise CandidatePayloadError("CANDIDATE_RUNTIME_HASH_REQUIRED")

        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise CandidatePayloadError("CANDIDATE_CONTENT_FILE_MISSING")
        raw = path.read_bytes()
        actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual_hash != content_hash:
            raise CandidatePayloadError("CANDIDATE_CONTENT_HASH_MISMATCH")

        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidatePayloadError("CANDIDATE_CONTENT_JSON_INVALID") from exc
        if not isinstance(envelope, dict):
            raise CandidatePayloadError("CANDIDATE_ENVELOPE_MUST_BE_OBJECT")
        if envelope.get("task_id") != producer_task_id:
            raise CandidatePayloadError("CANDIDATE_ENVELOPE_TASK_MISMATCH")
        declared_artifact = envelope.get("artifact")
        if not isinstance(declared_artifact, dict):
            raise CandidatePayloadError("CANDIDATE_ENVELOPE_ARTIFACT_REQUIRED")
        if declared_artifact.get("artifact_id") != artifact_id:
            raise CandidatePayloadError("CANDIDATE_ENVELOPE_ARTIFACT_ID_MISMATCH")
        if declared_artifact.get("artifact_type") != artifact_type:
            raise CandidatePayloadError("CANDIDATE_ENVELOPE_ARTIFACT_TYPE_MISMATCH")

        semantic_payload = envelope.get("semantic_payload")
        if not isinstance(semantic_payload, dict) or not semantic_payload:
            raise CandidatePayloadError("CANDIDATE_SEMANTIC_PAYLOAD_REQUIRED")
        if "evaluation" in semantic_payload or "task_state" in semantic_payload:
            raise CandidatePayloadError("CANDIDATE_WORKER_ACCEPTANCE_FIELDS_FORBIDDEN")

        return CandidatePayload(
            artifact_id=artifact_id,
            mission_id=mission_id,
            producer_task_id=producer_task_id,
            artifact_type=artifact_type,
            content_ref=content_ref,
            content_hash=content_hash,
            semantic_payload=dict(semantic_payload),
            envelope=dict(envelope),
        )