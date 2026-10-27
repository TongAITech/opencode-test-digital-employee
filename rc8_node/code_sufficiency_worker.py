"""Fail-closed N3 CODE_SUFFICIENCY node worker.

The worker evaluates exactly one frozen CODE_ANALYSIS artifact, publishes a
NODE_OBSERVATION_ONLY policy artifact and R1 attempt evidence, then completes
the leased WorkItem. Center remains the sole verification/sufficiency PASS
authority; this worker never writes a final Center verdict.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

_REQUIRED_ANALYSIS_KEYS = ("changed_files", "graph_evidence", "sufficiency")


@dataclass(frozen=True)
class CodeSufficiencyObservation:
    sufficient: bool
    missing: Sequence[str]
    source_artifact_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"authority": "NODE_OBSERVATION_ONLY", "sufficient": self.sufficient,
                "missing": list(self.missing), "source_artifact_id": self.source_artifact_id}


class CodeSufficiencyPolicy:
    version = "rc8.code-sufficiency.v1"

    @staticmethod
    def evaluate(artifact_id: str, analysis: Mapping[str, Any]) -> CodeSufficiencyObservation:
        if not str(artifact_id or "").strip():
            raise ValueError("CODE_ANALYSIS_ARTIFACT_ID_REQUIRED")
        if not isinstance(analysis, Mapping):
            raise ValueError("CODE_ANALYSIS_ARTIFACT_OBJECT_REQUIRED")
        missing = [key for key in _REQUIRED_ANALYSIS_KEYS if key not in analysis]
        changed_files = analysis.get("changed_files")
        graph_evidence = analysis.get("graph_evidence")
        sufficiency = analysis.get("sufficiency")
        if not isinstance(changed_files, list) or not changed_files:
            missing.append("changed_files:non-empty")
        if not isinstance(graph_evidence, list) or not graph_evidence:
            missing.append("graph_evidence:non-empty")
        if not isinstance(sufficiency, Mapping):
            missing.append("sufficiency:object")
        else:
            if sufficiency.get("sufficient") is not True:
                missing.append("sufficiency:sufficient=true")
            if sufficiency.get("unresolved"):
                missing.append("sufficiency:unresolved-empty")
        deduped = tuple(dict.fromkeys(missing))
        return CodeSufficiencyObservation(not deduped, deduped, str(artifact_id))


class CodeSufficiencyWorkerError(RuntimeError):
    pass


class CodeSufficiencyWorker:
    producer_ref = "RC8_CODE_SUFFICIENCY_WORKER"

    def __init__(self, *, agent: Any, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        identity = work.get("identity") if isinstance(work, dict) else None
        if not isinstance(identity, dict):
            raise CodeSufficiencyWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "CODE_SUFFICIENCY":
            raise CodeSufficiencyWorkerError("WORK_ITEM_STAGE_NOT_CODE_SUFFICIENCY")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        source_ref, source_id, analysis = self._load_analysis(work_item_id, lease_id, refs)
        observation = CodeSufficiencyPolicy.evaluate(source_id, analysis)

        self.agent.start(work_item_id, lease_id=lease_id)
        payload = {"schema_version": "rc8.code-sufficiency-observation.v1",
                   "policy_version": CodeSufficiencyPolicy.version,
                   "test_run_id": test_run_id, "work_item_id": work_item_id,
                   "stage_instance_id": stage_instance_id, "source_artifact_ref": source_ref,
                   "generated_at": self._now(), **observation.as_dict()}
        artifact_id = "artifact-code-suff-%s" % uuid.uuid4().hex
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="CODE_SUFFICIENCY_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            file_name="code-sufficiency-observation.json", sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), attempt_id=lease_id,
            refs=list(refs) + [source_ref, "stage:%s" % stage_instance_id],
            metadata={"stage": "CODE_SUFFICIENCY", "authority": "NODE_OBSERVATION_ONLY",
                      "policy_version": CodeSufficiencyPolicy.version}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        artifact_ref = "artifact:%s" % artifact_id
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-code-suff-%s" % uuid.uuid4().hex, test_run_id=test_run_id,
            work_item_id=work_item_id, node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED", sequence=self._next_sequence(test_run_id),
            attempt_id=lease_id, refs=list(refs),
            data={"stage_instance_id": stage_instance_id, "evidence_refs": [artifact_ref],
                  "source_artifact_ref": source_ref, "candidate_sufficient": observation.sufficient,
                  "missing": list(observation.missing), "authority": "NODE_OBSERVATION_ONLY"}),
            lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "artifact_ref": artifact_ref,
                "candidate_sufficient": observation.sufficient, "missing": list(observation.missing),
                "terminal": terminal}

    def _load_analysis(self, work_item_id: str, lease_id: str, refs: Sequence[str]) -> Tuple[str, str, Dict[str, Any]]:
        candidates = []
        headers = {"X-RC8-Node-Id": self.agent.identity.node_id, "X-RC8-Lease-Id": lease_id}
        for ref in refs:
            if not ref.startswith("artifact:"):
                continue
            artifact_id = ref.split(":", 1)[1]
            payload = self.agent.center.get("/api/v1/artifacts/%s/json?work_item_id=%s" %
                (quote(artifact_id, safe=""), quote(work_item_id, safe="")), headers=headers)
            content = payload.get("content")
            if isinstance(content, dict) and self._looks_like_code_analysis(content):
                candidates.append((ref, artifact_id, content))
        if len(candidates) != 1:
            raise CodeSufficiencyWorkerError("CODE_ANALYSIS_ARTIFACT_REQUIRED_EXACTLY_ONCE")
        return candidates[0]

    @staticmethod
    def _looks_like_code_analysis(content: Mapping[str, Any]) -> bool:
        return all(key in content for key in _REQUIRED_ANALYSIS_KEYS)

    def _next_sequence(self, test_run_id: str) -> int:
        payload = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" %
            (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        value = payload.get("next_sequence")
        if not isinstance(value, int) or value < 0:
            raise CodeSufficiencyWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return value

    @staticmethod
    def _required(value: Any, error: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise CodeSufficiencyWorkerError(error)
        return value
