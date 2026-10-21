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

from rc8_runtime import ArtifactAvailability, CapabilityQualification, CapabilityState, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest


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

    def qualify_through_center(
        self,
        agent,
        *,
        test_run_id: str,
        work_item_id: str,
        artifact_id: str,
        verified_at: Optional[int] = None,
    ) -> CapabilityQualification:
        """Probe, upload immutable evidence through the leased Center path, then VERIFY.

        The caller must already own an active qualification WorkItem lease. This
        deliberately reuses the same authorization boundary as runtime evidence;
        a node cannot self-assert VERIFIED without Center accepting the artifact.
        """
        result = self.probe()
        preliminary = self.qualification_before_upload(agent.identity.node_id, result)
        agent.report_capability(preliminary)
        if result.state != CapabilityState.PROBING or result.returncode != 0:
            return preliminary

        evidence = Path(result.evidence_path)
        content_size = evidence.stat().st_size
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=agent.identity.node_id,
            kind="CAPABILITY_PROBE",
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref=self.capability_id,
            file_name=evidence.name,
            sha256=result.sha256,
            size_bytes=content_size,
            availability=ArtifactAvailability.PENDING_UPLOAD,
            refs=["capability:%s" % self.capability_id],
            metadata={"probe_returncode": result.returncode, "probe_finished_at": result.finished_at},
        )
        completed = agent.upload_artifact_file(manifest, result.evidence_path)
        artifact = completed.get("artifact") if isinstance(completed, dict) else None
        if not isinstance(artifact, dict) or artifact.get("availability") != ArtifactAvailability.AVAILABLE.value:
            raise CapabilityAdapterError("CAPABILITY_EVIDENCE_NOT_AVAILABLE")
        if artifact.get("artifact_id") != artifact_id:
            raise CapabilityAdapterError("CAPABILITY_EVIDENCE_ARTIFACT_MISMATCH")

        verified = self.verified_qualification(
            agent.identity.node_id,
            result,
            artifact_id,
            verified_at=verified_at,
        )
        agent.report_capability(verified)
        return verified
