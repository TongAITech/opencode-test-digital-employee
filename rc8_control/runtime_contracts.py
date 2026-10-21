"""RC8 transport contracts layered on top of RC7 R1 truth.

These contracts do not create a second runtime truth.  They carry identity and
artifact metadata between a DSH node and Center while preserving the source R1
event identity/sequence needed for deterministic ingestion and replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import RC8ContractError, _required, _string_list


class ArtifactAvailability(str, Enum):
    DECLARED = "DECLARED"
    UPLOADING = "UPLOADING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class RuntimeEventEnvelope:
    event_id: str
    test_run_id: str
    mission_id: str
    work_item_id: str
    node_id: str
    event_type: str
    subject_type: str
    subject_id: str
    source_r1_event_id: str
    source_r1_seq: int
    idempotency_key: str
    refs: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "test_run_id",
            "mission_id",
            "work_item_id",
            "node_id",
            "event_type",
            "subject_type",
            "subject_id",
            "source_r1_event_id",
            "idempotency_key",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.source_r1_seq, int) or self.source_r1_seq < 1:
            raise RC8ContractError("SOURCE_R1_SEQ_INVALID")
        _string_list(self.refs, "refs")
        if not isinstance(self.data, dict):
            raise RC8ContractError("EVENT_DATA_MUST_BE_OBJECT")


@dataclass
class ArtifactManifest:
    artifact_id: str
    artifact_type: str
    test_run_id: str
    mission_id: str
    work_item_id: str
    node_id: str
    producer_ref: str
    file_name: str
    size_bytes: int
    sha256: str
    availability: ArtifactAvailability = ArtifactAvailability.DECLARED
    case_id: Optional[str] = None
    attempt_id: Optional[str] = None
    step_id: Optional[str] = None
    assertion_id: Optional[str] = None
    subject_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "artifact_type",
            "test_run_id",
            "mission_id",
            "work_item_id",
            "node_id",
            "producer_ref",
            "file_name",
            "sha256",
        ):
            setattr(self, name, _required(getattr(self, name), name))
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise RC8ContractError("ARTIFACT_SIZE_INVALID")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in self.sha256):
            raise RC8ContractError("ARTIFACT_SHA256_INVALID")
        _string_list(self.subject_refs, "subject_refs")
        if not isinstance(self.metadata, dict):
            raise RC8ContractError("ARTIFACT_METADATA_MUST_BE_OBJECT")
        if self.assertion_id and not self.step_id:
            raise RC8ContractError("ASSERTION_ARTIFACT_REQUIRES_STEP_ID")
        if self.step_id and not self.attempt_id:
            raise RC8ContractError("STEP_ARTIFACT_REQUIRES_ATTEMPT_ID")
        if self.attempt_id and not self.case_id:
            raise RC8ContractError("ATTEMPT_ARTIFACT_REQUIRES_CASE_ID")

    @property
    def is_available(self) -> bool:
        return self.availability == ArtifactAvailability.AVAILABLE

    @property
    def is_assertion_evidence(self) -> bool:
        return bool(self.assertion_id and self.step_id and self.attempt_id and self.case_id)
