"""Real RC8 node capability adapters.

Adapters execute local tools through subprocess. A capability is never VERIFIED
from installation/presence alone: probe output is persisted as evidence and the
caller must upload/bind it before reporting VERIFIED to Center.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rc8_runtime import CapabilityQualification, CapabilityState


class CapabilityAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeResult:
    capability_id: str
    state: CapabilityState
    command: List[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    started_at: int
    finished_at: int
    evidence_path: str
    sha256: str


class MavenJUnitCapabilityAdapter:
    """Probe the real Maven/JUnit harness available on an execution node."""

    capability_id = "maven-junit"

    def __init__(self, evidence_dir: str, *, maven_command: Optional[str] = None, timeout_seconds: int = 30) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.maven_command = (maven_command or os.environ.get("RC8_MVN") or "mvn").strip()
        self.timeout_seconds = timeout_seconds
        if not self.maven_command:
            raise CapabilityAdapterError("MAVEN_COMMAND_REQUIRED")

    def probe(self) -> ProbeResult:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        command = [self.maven_command, "-version"]
        started = int(time.time())
        returncode: Optional[int] = None
        stdout = ""
        stderr = ""
        state = CapabilityState.UNAVAILABLE
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
            returncode = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            state = CapabilityState.PROBING if returncode == 0 else CapabilityState.DEGRADED
        except FileNotFoundError as exc:
            stderr = str(exc)
        except subprocess.TimeoutExpired as exc:
            state = CapabilityState.DEGRADED
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = "MAVEN_PROBE_TIMEOUT"

        finished = int(time.time())
        payload: Dict[str, object] = {
            "schema_version": 1,
            "capability_id": self.capability_id,
            "command": command,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "started_at": started,
            "finished_at": finished,
            "probe_state": state.value,
            "truth_note": "PROBING is not VERIFIED until this evidence is uploaded and bound by Center",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        path = self.evidence_dir / "maven-junit-probe.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_bytes(encoded)
        os.replace(str(temp), str(path))
        digest = hashlib.sha256(encoded).hexdigest()
        return ProbeResult(self.capability_id, state, command, returncode, stdout, stderr, started, finished, str(path), digest)

    @staticmethod
    def qualification_before_upload(node_id: str, result: ProbeResult) -> CapabilityQualification:
        """Report probe outcome without falsely claiming VERIFIED."""
        return CapabilityQualification(
            node_id=node_id,
            capability_id=result.capability_id,
            state=result.state,
            probe_ref=result.evidence_path,
            evidence_refs=[],
            verified_at=None,
        )

    @staticmethod
    def verified_qualification(node_id: str, result: ProbeResult, artifact_id: str, *, verified_at: Optional[int] = None) -> CapabilityQualification:
        if result.state != CapabilityState.PROBING or result.returncode != 0:
            raise CapabilityAdapterError("CAPABILITY_PROBE_NOT_SUCCESSFUL")
        if not artifact_id.strip():
            raise CapabilityAdapterError("CAPABILITY_EVIDENCE_ARTIFACT_REQUIRED")
        return CapabilityQualification(
            node_id=node_id,
            capability_id=result.capability_id,
            state=CapabilityState.VERIFIED,
            probe_ref=result.evidence_path,
            evidence_refs=[artifact_id.strip()],
            verified_at=int(verified_at if verified_at is not None else time.time()),
        )
