"""Fail-closed N6 EXECUTABLE_SPEC node worker.

Builds a candidate executable specification bound to one N5 PreparedAttempt.
Canonical ExecutableReadiness BUILT/VERIFIED/READY remains Center authority.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

from .dsh_json_runner import DshJsonRunner, DshJsonRunnerError


class ExecutableSpecWorkerError(RuntimeError):
    pass


class ExecutableSpecWorker:
    producer_ref = "RC8_EXECUTABLE_SPEC_WORKER"

    def __init__(self, *, agent: Any, dsh_runner: DshJsonRunner, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        identity = work.get("identity") if isinstance(work, dict) else None
        if not isinstance(identity, dict):
            raise ExecutableSpecWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "EXECUTABLE_SPEC":
            raise ExecutableSpecWorkerError("WORK_ITEM_STAGE_NOT_EXECUTABLE_SPEC")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise ExecutableSpecWorkerError("N6_FROZEN_SCOPE_REFS_REQUIRED")
        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise ExecutableSpecWorkerError("EXECUTABLE_SPEC_DSH_FAILED:%s" % exc.reason)
        payload = {"schema_version": "rc8.executable-spec-observation.v1", "authority": "NODE_OBSERVATION_ONLY",
                   "test_run_id": test_run_id, "work_item_id": work_item_id, "stage_instance_id": stage_instance_id,
                   "scope_refs": list(refs), "candidate": candidate, "dsh_session_id": result.session_id,
                   "tool_calls": list(result.tool_calls), "generated_at": self._now()}
        artifact_id = "artifact-executable-spec-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-executable-spec-%s" % uuid.uuid4().hex, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED", sequence=self._next_sequence(test_run_id), attempt_id=lease_id,
            refs=list(refs), data={"stage_instance_id": stage_instance_id, "evidence_refs": [artifact_ref],
                "executable_readiness_authority": "CENTER_ONLY", "prepared_attempt_id": candidate["prepared_attempt_id"],
                "authority": "NODE_OBSERVATION_ONLY", "finished_at": self._now()}), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref,
                "executable_readiness_authority": "CENTER_ONLY", "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ExecutableSpecWorkerError("EXECUTABLE_SPEC_OUTPUT_OBJECT_REQUIRED")
        required = ("prepared_attempt_id", "frozen_case_ref", "driver_ref", "script_artifact_ref")
        for name in required:
            if not str(value.get(name) or "").strip():
                raise ExecutableSpecWorkerError("%s_REQUIRED" % name.upper())
        for name in ("fixture_binding_refs", "assertion_refs", "evidence_collector_refs", "build_evidence_refs"):
            refs = value.get(name)
            if not isinstance(refs, list) or not refs or any(not str(v).strip() for v in refs):
                raise ExecutableSpecWorkerError("%s_NONEMPTY_REQUIRED" % name.upper())
            if len(set(str(v).strip() for v in refs)) != len(refs):
                raise ExecutableSpecWorkerError("%s_UNIQUE_REQUIRED" % name.upper())
        return dict(value)

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="EXECUTABLE_SPEC_OBSERVATION", producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref, file_name="executable-spec-observation.json", sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "EXECUTABLE_SPEC", "authority": "NODE_OBSERVATION_ONLY",
                      "executable_readiness_authority": "CENTER_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" %
            (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise ExecutableSpecWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(refs: Sequence[str]) -> str:
        return ("You are RC8 N6 EXECUTABLE_SPEC. Use only frozen refs %s and the exact current N5 PreparedAttempt. Return strict JSON "
                "with prepared_attempt_id, frozen_case_ref, driver_ref, script_artifact_ref, fixture_binding_refs, assertion_refs, "
                "evidence_collector_refs and build_evidence_refs. All ref lists must be non-empty. Do not claim executable READY, "
                "test PASS, quality or release; Center owns readiness and final authority." % json.dumps(list(refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ExecutableSpecWorkerError(error)
        return normalized
