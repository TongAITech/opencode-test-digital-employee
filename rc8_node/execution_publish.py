"""Publish real Maven/JUnit execution truth through the RC8 Node -> Center boundary.

The execution adapter produces Actual from JUnit XML. This publisher uploads the
machine evidence first and only then appends a canonical R1 runtime event that
references the AVAILABLE artifacts. It never derives PASS from model text.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List

from rc8_runtime import ArtifactAvailability, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest

from .agent import NodeAgent, NodeAgentError
from .execution import MavenExecutionResult


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _artifact_id(work_item_id: str, role: str, path: Path) -> str:
    seed = (work_item_id + "|" + role + "|" + _sha256(path)).encode("utf-8")
    return "exec-%s-%s" % (role, hashlib.sha256(seed).hexdigest()[:20])


def publish_maven_junit_execution(
    agent: NodeAgent,
    *,
    test_run_id: str,
    work_item_id: str,
    result: MavenExecutionResult,
    event_id: str,
    sequence: int,
) -> Dict[str, object]:
    """Upload execution evidence and append one evidence-bound runtime Actual event."""
    files: List[tuple] = [
        ("actual", Path(result.result_path), "application/json"),
        ("stdout", Path(result.stdout_path), "text/plain"),
        ("stderr", Path(result.stderr_path), "text/plain"),
    ]
    files.extend(("junit", Path(path), "application/xml") for path in result.actual.xml_files)

    artifact_ids: List[str] = []
    for role, path, media_type in files:
        if not path.is_file():
            raise NodeAgentError("EXECUTION_EVIDENCE_FILE_MISSING:%s" % path)
        artifact_id = _artifact_id(work_item_id, role, path)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=agent.identity.node_id,
            kind="maven-junit-%s" % role,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="rc8:maven-junit",
            file_name=path.name,
            sha256=_sha256(path),
            size_bytes=path.stat().st_size,
            availability=ArtifactAvailability.PENDING_UPLOAD,
            refs=[],
            metadata={"media_type": media_type, "truth_role": role},
        )
        completed = agent.upload_artifact_file(manifest, str(path))
        availability = str(completed.get("availability") or completed.get("status") or "")
        if "AVAILABLE" not in availability.upper():
            raise NodeAgentError("EXECUTION_EVIDENCE_NOT_AVAILABLE:%s" % artifact_id)
        artifact_ids.append(artifact_id)

    actual = result.actual
    event = RuntimeEventEnvelope(
        event_id=event_id,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        node_id=agent.identity.node_id,
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="rc8:maven-junit",
        event_type="MAVEN_JUNIT_ACTUAL_RECORDED",
        sequence=sequence,
        refs=artifact_ids,
        data={
            "tests": actual.tests,
            "failures": actual.failures,
            "errors": actual.errors,
            "skipped": actual.skipped,
            "passed": actual.passed,
            "maven_returncode": result.returncode,
            "assertion": "tests>0 and failures==0 and errors==0",
            "truth_source": "JUnit XML",
        },
    )
    response = agent.append_runtime_event(event)
    return {"event_id": event_id, "artifact_ids": artifact_ids, "actual_passed": actual.passed, "center": response}
