"""Generic RC8 artifact-transfer contracts.

Evidence is one use of an artifact; scripts, data assets, skill candidates and
knowledge-candidate attachments use the same transfer protocol without being
mislabelled as PASS evidence.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .contracts import ArtifactAvailability, RC8ContractError, RuntimeProducerKind, _nonnegative, _required, _strings


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    test_run_id: str
    work_item_id: str
    node_id: str
    kind: str
    producer_kind: RuntimeProducerKind
    producer_ref: str
    file_name: str
    sha256: str
    size_bytes: int
    availability: ArtifactAvailability = ArtifactAvailability.PENDING_UPLOAD
    case_id: Optional[str] = None
    attempt_id: Optional[str] = None
    step_id: Optional[str] = None
    refs: List[str] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "test_run_id",
            "work_item_id",
            "node_id",
            "kind",
            "producer_ref",
            "file_name",
            "sha256",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.producer_kind, RuntimeProducerKind):
            raise RC8ContractError("ARTIFACT_PRODUCER_KIND_INVALID")
        if not isinstance(self.availability, ArtifactAvailability):
            raise RC8ContractError("ARTIFACT_AVAILABILITY_INVALID")
        if not re.match(r"^[A-Za-z0-9._-]+$", self.artifact_id):
            raise RC8ContractError("ARTIFACT_ID_UNSAFE")
        if not re.match(r"^[0-9a-fA-F]{64}$", self.sha256):
            raise RC8ContractError("ARTIFACT_SHA256_INVALID")
        _nonnegative(self.size_bytes, "size_bytes")
        object.__setattr__(self, "refs", _strings(self.refs, "refs"))
        if not isinstance(self.metadata, dict):
            raise RC8ContractError("ARTIFACT_METADATA_MUST_BE_OBJECT")
        for name in ("case_id", "attempt_id", "step_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RC8ContractError("%s_INVALID" % name.upper())
