"""Runtime-owned Reality Recon for Mission Graph v2.

Reality Recon is not a free AI-worker stage. Runtime canonicalizes repository,
release, runtime-profile and source-revision facts, persists the immutable
snapshot/evidence into the same R1 truth boundary, and only then releases the
Requirement Analysis producer.

The collector and verifier use distinct runtime identities. This is not a
Requirement/Code/Test sufficiency decision; those remain independent authority
gates and cannot be self-issued by their producer workers.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .mission_graph import MissionTaskGraphCompiler
from .models import Artifact, Evaluation, EvaluationResult, Evidence, TaskStatus


class RuntimeRealityReconError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _canonical_json(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeRealityReconError("REALITY_FACTS_NOT_JSON_SERIALIZABLE") from exc


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)


@dataclass(frozen=True)
class RuntimeRealitySnapshot:
    task_id: str
    artifact_id: str
    content_ref: str
    content_hash: str
    evidence_ids: Tuple[str, ...]
    task_state: str


class RuntimeRealityReconService:
    COLLECTOR_REF = "rc7-runtime-reality-collector"
    VERIFIER_REF = "rc7-runtime-reality-verifier"
    REQUIRED_FACTS = ("release_id", "source_revision", "repository_ref", "runtime_profile")

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def reconcile(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        facts: Mapping[str, Any],
        evidence_refs: Sequence[str],
    ) -> RuntimeRealitySnapshot:
        compiler = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V2)
        graph = compiler.compile(control.mission_id)
        expected = graph.task("REALITY_RECON")
        task = control.scheduler.task(task_id)
        if task.task_id != expected.task_id or task.node != "REALITY_RECON" or task.task_type != "RUNTIME":
            raise RuntimeRealityReconError("REALITY_RECON_RUNTIME_TASK_REQUIRED")

        normalized_facts = self._validate_facts(control, facts)
        normalized_refs = self._validate_evidence_refs(evidence_refs)
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "owner": "RUNTIME",
            "facts": normalized_facts,
            "evidence_refs": list(normalized_refs),
        }
        encoded = _canonical_json(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        content_hash = "sha256:" + digest
        artifact_id = graph.artifact_ids["REALITY_RECON"]
        path = self._snapshot_path(control.mission_id, digest)

        existing = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if existing:
            if len(existing) != 1:
                raise RuntimeRealityReconError("REALITY_SNAPSHOT_ARTIFACT_NOT_UNIQUE")
            return self._resume_existing(
                control,
                task_id=task_id,
                artifact_id=artifact_id,
                row=existing[0],
                expected_bytes=encoded,
                expected_hash=content_hash,
            )

        if task.state != TaskStatus.READY:
            raise RuntimeRealityReconError("REALITY_RECON_REQUIRES_READY_TASK")
        leased = control.lease_next(
            worker_ref=self.COLLECTOR_REF,
            capabilities=task.required_capabilities,
        )
        if leased is None or leased.task_id != task_id:
            raise RuntimeRealityReconError("REALITY_RECON_LEASE_MISMATCH")
        running = control.start(task_id, worker_ref=self.COLLECTOR_REF)
        if running.state != TaskStatus.RUNNING:
            raise RuntimeRealityReconError("REALITY_RECON_DID_NOT_START")

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_FILE_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence = [
            Evidence(
                evidence_id=_stable_id("EVD-REALITY-SOURCE", control.mission_id, ref),
                mission_id=control.mission_id,
                kind="REALITY_SOURCE_PROOF",
                source_ref="runtime://reality-recon",
                content_ref=ref,
                subject_refs=[task_id, artifact_id],
            )
            for ref in normalized_refs
        ]
        record = Evidence(
            evidence_id=_stable_id("EVD-REALITY-RECORD", control.mission_id, digest),
            mission_id=control.mission_id,
            kind="RUNTIME_REALITY_SNAPSHOT",
            source_ref="runtime://reality-recon",
            content_ref="file://" + str(path),
            subject_refs=[task_id, artifact_id],
            content_hash=content_hash,
        )
        evidence.append(record)
        evidence_ids = tuple(item.evidence_id for item in evidence)

        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=compiler.OUTPUT_TYPES["REALITY_RECON"],
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=list(task.input_artifact_refs),
            evidence_refs=list(evidence_ids),
            content_hash=content_hash,
        )
        candidate = control.submit_worker_output(
            WorkerOutput(
                task_id=task_id,
                worker_ref=self.COLLECTOR_REF,
                artifacts=(artifact,),
                evidence=tuple(evidence),
            )
        )
        if candidate.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeRealityReconError("REALITY_RECON_OUTPUT_NOT_DURABLE")

        self._accept_runtime_verification(
            control,
            task_id=task_id,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            digest=digest,
            fact_keys=tuple(sorted(normalized_facts)),
        )
        current = control.scheduler.task(task_id)
        return RuntimeRealitySnapshot(
            task_id=task_id,
            artifact_id=artifact_id,
            content_ref=artifact.content_ref,
            content_hash=content_hash,
            evidence_ids=evidence_ids,
            task_state=current.state.value,
        )

    def _resume_existing(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        row: Mapping[str, Any],
        expected_bytes: bytes,
        expected_hash: str,
    ) -> RuntimeRealitySnapshot:
        if row.get("mission_id") != control.mission_id or row.get("producer_task_id") != task_id:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_OWNERSHIP_MISMATCH")
        if row.get("content_hash") != expected_hash:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_INPUT_DRIFT")
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_CONTENT_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file() or path.read_bytes() != expected_bytes:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_CONTENT_MISMATCH")
        evidence_ids = tuple(row.get("evidence_refs", ()))
        if not evidence_ids:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_EVIDENCE_REQUIRED")
        for evidence_id in evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise RuntimeRealityReconError("REALITY_SNAPSHOT_EVIDENCE_NOT_DURABLE")

        task = control.scheduler.task(task_id)
        if task.state == TaskStatus.OUTPUT_PRODUCED:
            digest = expected_hash.split(":", 1)[-1]
            self._accept_runtime_verification(
                control,
                task_id=task_id,
                artifact_id=artifact_id,
                evidence_ids=evidence_ids,
                digest=digest,
                fact_keys=(),
            )
            task = control.scheduler.task(task_id)
        if task.state != TaskStatus.PASS:
            raise RuntimeRealityReconError("REALITY_SNAPSHOT_EXISTS_WITH_NONPASS_TASK")
        return RuntimeRealitySnapshot(
            task_id=task_id,
            artifact_id=artifact_id,
            content_ref=content_ref,
            content_hash=expected_hash,
            evidence_ids=evidence_ids,
            task_state=task.state.value,
        )

    def _accept_runtime_verification(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        evidence_ids: Sequence[str],
        digest: str,
        fact_keys: Sequence[str],
    ) -> None:
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-REALITY", control.mission_id, digest),
            mission_id=control.mission_id,
            node="REALITY_RECON",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=self.VERIFIER_REF,
            dimensions={
                "runtime_owned": True,
                "snapshot_sha256": digest,
                "fact_keys": list(fact_keys),
                "sufficiency_authority": False,
            },
            evidence_refs=list(evidence_ids),
        )
        accepted = control.accept_evaluation(task_id, evaluation=evaluation)
        if accepted.state != TaskStatus.PASS:
            raise RuntimeRealityReconError("REALITY_RECON_VERIFICATION_DID_NOT_PASS")

    def _validate_facts(self, control: ClosedLoopControlPlane, facts: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(facts, Mapping):
            raise RuntimeRealityReconError("REALITY_FACTS_MAPPING_REQUIRED")
        normalized = dict(facts)
        missing = [key for key in self.REQUIRED_FACTS if not isinstance(normalized.get(key), str) or not str(normalized.get(key)).strip()]
        if missing:
            raise RuntimeRealityReconError("REALITY_FACTS_REQUIRED:%s" % ",".join(missing))
        if str(normalized["release_id"]).strip() != control.release_id:
            raise RuntimeRealityReconError("REALITY_RELEASE_MISMATCH")
        return normalized

    @staticmethod
    def _validate_evidence_refs(values: Sequence[str]) -> Tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise RuntimeRealityReconError("REALITY_EVIDENCE_REFS_SEQUENCE_REQUIRED")
        refs = tuple(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))
        if not refs:
            raise RuntimeRealityReconError("REALITY_EVIDENCE_REQUIRED")
        return refs

    def _snapshot_path(self, mission_id: str, digest: str) -> Path:
        return self.evidence_root / "reality-recon" / _safe_name(mission_id) / (digest + ".json")
