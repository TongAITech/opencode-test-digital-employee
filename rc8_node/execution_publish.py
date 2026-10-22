"""Publish real Maven/JUnit/JaCoCo execution truth through Node -> Center.

Machine evidence is uploaded first. Runtime facts are appended only after every
referenced artifact is AVAILABLE. JaCoCo changed-scope Actual becomes canonical
COVERAGE_COLLECTED events. Coverage deficits become explicit COVERAGE_GAP facts
routed back to TEST_DESIGN; neither coverage nor a gap directly decides
Layer/Mission PASS.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from rc8_runtime import ArtifactAvailability, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import CoverageDimension, GapSeverity, GapType, route_gap

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


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(seed).hexdigest()[:24])


def _completed_artifact(response: Dict[str, object], artifact_id: str) -> Dict[str, object]:
    artifact = response.get("artifact") if isinstance(response, dict) else None
    if artifact is None:
        artifact = response
    if not isinstance(artifact, dict):
        raise NodeAgentError("EXECUTION_EVIDENCE_RESPONSE_INVALID:%s" % artifact_id)
    if str(artifact.get("artifact_id") or artifact_id) != artifact_id:
        raise NodeAgentError("EXECUTION_EVIDENCE_ARTIFACT_MISMATCH:%s" % artifact_id)
    availability = str(artifact.get("availability") or artifact.get("status") or "")
    if availability.upper() != ArtifactAvailability.AVAILABLE.value:
        raise NodeAgentError("EXECUTION_EVIDENCE_NOT_AVAILABLE:%s" % artifact_id)
    return artifact


@dataclass(frozen=True)
class CoveragePublishContext:
    stage_instance_id: str
    attempt_id: str
    subject_ref: str
    thresholds: Mapping[str, float] = field(default_factory=lambda: {
        CoverageDimension.CHANGED_METHOD.value: 1.0,
        CoverageDimension.CHANGED_LINE.value: 1.0,
        CoverageDimension.CHANGED_BRANCH.value: 1.0,
    })

    def __post_init__(self) -> None:
        for name in ("stage_instance_id", "attempt_id", "subject_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s_REQUIRED" % name.upper())
        normalized: Dict[str, float] = {}
        for dimension in (
            CoverageDimension.CHANGED_METHOD,
            CoverageDimension.CHANGED_LINE,
            CoverageDimension.CHANGED_BRANCH,
        ):
            raw = self.thresholds.get(dimension.value, 1.0)
            threshold = float(raw)
            if threshold < 0.0 or threshold > 1.0:
                raise ValueError("COVERAGE_THRESHOLD_INVALID:%s" % dimension.value)
            normalized[dimension.value] = threshold
        object.__setattr__(self, "thresholds", normalized)


def _coverage_actual(result: MavenExecutionResult, dimension: CoverageDimension) -> Tuple[int, int]:
    if result.coverage is None:
        raise NodeAgentError("COVERAGE_RESULT_REQUIRED")
    if dimension == CoverageDimension.CHANGED_METHOD:
        actual = result.coverage.changed_method
    elif dimension == CoverageDimension.CHANGED_LINE:
        actual = result.coverage.changed_line
    elif dimension == CoverageDimension.CHANGED_BRANCH:
        actual = result.coverage.changed_branch
    else:
        raise NodeAgentError("COVERAGE_DIMENSION_UNSUPPORTED:%s" % dimension.value)
    return actual.covered, actual.total


def _coverage_ratio(covered: int, total: int) -> float:
    return 1.0 if total == 0 else float(covered) / float(total)


def publish_maven_junit_execution(
    agent: NodeAgent,
    *,
    test_run_id: str,
    work_item_id: str,
    result: MavenExecutionResult,
    event_id: str,
    sequence: int,
    coverage_context: Optional[CoveragePublishContext] = None,
) -> Dict[str, object]:
    """Upload evidence, append execution Actual, coverage facts and governed gaps."""
    if result.coverage is not None and coverage_context is None:
        raise NodeAgentError("COVERAGE_PUBLISH_CONTEXT_REQUIRED")
    if coverage_context is not None and result.coverage is None and result.coverage_required:
        # The failed execution Actual may still be published for diagnosis, but
        # no COVERAGE_COLLECTED/GAP_OPENED event may be manufactured without
        # fresh JaCoCo Actual.
        pass

    files: List[tuple] = [
        ("actual", Path(result.result_path), "application/json"),
        ("stdout", Path(result.stdout_path), "text/plain"),
        ("stderr", Path(result.stderr_path), "text/plain"),
    ]
    files.extend(("junit", Path(path), "application/xml") for path in result.actual.xml_files)
    if result.coverage is not None:
        files.append(("jacoco-actual", Path(result.coverage.result_path), "application/json"))
        files.extend(("jacoco-xml", Path(path), "application/xml") for path in result.coverage.reports)

    artifact_ids: List[str] = []
    artifact_ids_by_role: Dict[str, List[str]] = {}
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
        _completed_artifact(completed, artifact_id)
        artifact_ids.append(artifact_id)
        artifact_ids_by_role.setdefault(role, []).append(artifact_id)

    actual = result.actual
    truth_source = "Fresh JUnit XML + Maven process result"
    if result.coverage_required:
        truth_source += " + requested fresh JaCoCo changed-scope evidence"
    event = RuntimeEventEnvelope(
        event_id=event_id,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        node_id=agent.identity.node_id,
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="rc8:maven-junit",
        event_type="MAVEN_JUNIT_ACTUAL_RECORDED",
        sequence=sequence,
        attempt_id=coverage_context.attempt_id if coverage_context is not None else None,
        refs=artifact_ids,
        data={
            "tests": actual.tests,
            "failures": actual.failures,
            "errors": actual.errors,
            "skipped": actual.skipped,
            "junit_passed": actual.passed,
            "passed": result.execution_passed,
            "maven_returncode": result.returncode,
            "classification": result.classification,
            "stale_junit_reports_ignored": result.stale_xml_ignored,
            "coverage_required": result.coverage_required,
            "coverage_classification": result.coverage_classification,
            "stdout_encoding": result.stdout_encoding,
            "stderr_encoding": result.stderr_encoding,
            "assertion": "maven_returncode==0 and tests>0 and failures==0 and errors==0 and requested_coverage_available",
            "truth_source": truth_source,
        },
    )
    actual_response = agent.append_runtime_event(event)

    coverage_events: List[Dict[str, object]] = []
    gap_events: List[Dict[str, object]] = []
    if result.coverage is not None and coverage_context is not None:
        coverage_artifact_ids = list(dict.fromkeys(
            artifact_ids_by_role.get("jacoco-actual", []) + artifact_ids_by_role.get("jacoco-xml", [])
        ))
        if not coverage_artifact_ids:
            raise NodeAgentError("COVERAGE_ARTIFACTS_REQUIRED")
        dimensions = (
            CoverageDimension.CHANGED_METHOD,
            CoverageDimension.CHANGED_LINE,
            CoverageDimension.CHANGED_BRANCH,
        )
        deficits: List[Tuple[CoverageDimension, int, int, float]] = []
        for offset, dimension in enumerate(dimensions, start=1):
            covered, total = _coverage_actual(result, dimension)
            threshold = coverage_context.thresholds[dimension.value]
            ratio = _coverage_ratio(covered, total)
            observation_id = _stable_id(
                "covobs", test_run_id, work_item_id, coverage_context.attempt_id,
                result.coverage.source_snapshot_ref, dimension.value, result.coverage.sha256,
            )
            metric_id = _stable_id("covmetric", observation_id, dimension.value)
            coverage_event_id = "%s-coverage-%s" % (event_id, dimension.value.lower().replace("_", "-"))
            coverage_event = RuntimeEventEnvelope(
                event_id=coverage_event_id,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=agent.identity.node_id,
                producer_kind=RuntimeProducerKind.TOOL,
                producer_ref="rc8:jacoco",
                event_type="COVERAGE_COLLECTED",
                sequence=sequence + offset,
                attempt_id=coverage_context.attempt_id,
                refs=coverage_artifact_ids,
                data={
                    "observation_id": observation_id,
                    "stage_instance_id": coverage_context.stage_instance_id,
                    "subject_ref": coverage_context.subject_ref,
                    "source_snapshot_ref": result.coverage.source_snapshot_ref,
                    "source_tool": "jacoco",
                    "artifact_refs": coverage_artifact_ids,
                    "metric": {
                        "metric_id": metric_id,
                        "dimension": dimension.value,
                        "covered": covered,
                        "total": total,
                        "threshold": threshold,
                        "evidence_refs": coverage_artifact_ids,
                        "critical": True,
                    },
                },
            )
            response = agent.append_runtime_event(coverage_event)
            coverage_events.append({
                "event_id": coverage_event_id,
                "dimension": dimension.value,
                "observation_id": observation_id,
                "covered": covered,
                "total": total,
                "threshold": threshold,
                "ratio": ratio,
                "satisfied": ratio >= threshold,
                "center": response,
            })
            if ratio < threshold:
                deficits.append((dimension, covered, total, threshold))

        gap_owner = route_gap(GapType.COVERAGE_GAP)
        next_sequence = sequence + len(dimensions) + 1
        for index, (dimension, covered, total, threshold) in enumerate(deficits):
            ratio = _coverage_ratio(covered, total)
            gap_id = _stable_id(
                "gap", test_run_id, coverage_context.subject_ref,
                result.coverage.source_snapshot_ref, GapType.COVERAGE_GAP.value, dimension.value,
            )
            gap_event_id = "%s-gap-%s" % (event_id, dimension.value.lower().replace("_", "-"))
            gap_event = RuntimeEventEnvelope(
                event_id=gap_event_id,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=agent.identity.node_id,
                producer_kind=RuntimeProducerKind.TOOL,
                producer_ref="rc8:coverage-gap-evaluator",
                event_type="GAP_OPENED",
                sequence=next_sequence + index,
                attempt_id=coverage_context.attempt_id,
                refs=coverage_artifact_ids,
                data={
                    "gap_id": gap_id,
                    "source_stage_instance_id": coverage_context.stage_instance_id,
                    "gap_type": GapType.COVERAGE_GAP.value,
                    "severity": GapSeverity.P1.value,
                    "description": (
                        "%s coverage %s/%s (%.4f) below threshold %.4f for %s"
                        % (dimension.value, covered, total, ratio, threshold, coverage_context.subject_ref)
                    ),
                    "owner_stage": gap_owner,
                    "repair_strategy": "GENERATE_DELTA_TEST_THEN_TARGETED_RERUN",
                    "evidence_refs": coverage_artifact_ids,
                    "invalidates": [],
                    "coverage_dimension": dimension.value,
                    "covered": covered,
                    "total": total,
                    "ratio": ratio,
                    "threshold": threshold,
                    "source_snapshot_ref": result.coverage.source_snapshot_ref,
                },
            )
            response = agent.append_runtime_event(gap_event)
            gap_events.append({
                "event_id": gap_event_id,
                "gap_id": gap_id,
                "dimension": dimension.value,
                "owner_stage": gap_owner,
                "repair_strategy": "GENERATE_DELTA_TEST_THEN_TARGETED_RERUN",
                "center": response,
            })

    return {
        "event_id": event_id,
        "artifact_ids": artifact_ids,
        "actual_passed": result.execution_passed,
        "center": actual_response,
        "coverage_events": coverage_events,
        "gap_events": gap_events,
    }
