from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

from .code_analysis import EvidenceBackedCodeAnalysisEngine


class CodeAnalysisWorkerError(RuntimeError):
    pass


def _scope_value(scope_refs: Sequence[str], key: str) -> Optional[str]:
    prefix = key + ":"
    values = [str(ref)[len(prefix):].strip() for ref in scope_refs if str(ref).startswith(prefix) and str(ref)[len(prefix):].strip()]
    if len(values) > 1:
        raise CodeAnalysisWorkerError("%s_REF_AMBIGUOUS" % key.upper().replace("-", "_"))
    return values[0] if values else None


class CodeAnalysisWorker:
    producer_ref = "RC8_CODE_ANALYSIS_WORKER"

    def __init__(self, *, agent: Any, work_dir: str, codegraph_command: str) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.codegraph_command = str(codegraph_command or "").strip()
        if not self.codegraph_command:
            raise CodeAnalysisWorkerError("CODEGRAPH_COMMAND_REQUIRED")

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict) or not isinstance(work.get("identity"), dict):
            raise CodeAnalysisWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        identity = work["identity"]
        if str(identity.get("stage") or "") != "CODE_ANALYSIS":
            raise CodeAnalysisWorkerError("WORK_ITEM_STAGE_NOT_CODE_ANALYSIS")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(value).strip() for value in identity.get("scope_refs") or [] if str(value).strip())
        repo_path = _scope_value(refs, "repo-path")
        base_ref = _scope_value(refs, "git-base")
        head_ref = _scope_value(refs, "git-head")
        missing = [name for name, value in (("repo-path", repo_path), ("git-base", base_ref), ("git-head", head_ref)) if not value]
        if missing:
            raise CodeAnalysisWorkerError("IMMUTABLE_N3_SCOPE_REQUIRED:%s" % ",".join(missing))
        repo = Path(str(repo_path)).expanduser().resolve()
        if not repo.is_dir():
            raise CodeAnalysisWorkerError("REPO_PATH_NOT_DIRECTORY")

        self.agent.start(work_item_id, lease_id=lease_id)
        engine = EvidenceBackedCodeAnalysisEngine(
            str(self.work_dir / work_item_id / "evidence"),
            codegraph_command=self.codegraph_command,
        )
        result = engine.execute(repo_path=str(repo), base_ref=str(base_ref), head_ref=str(head_ref), context={"test_run_id": test_run_id, "work_item_id": work_item_id, "stage_instance_id": stage_instance_id})
        artifact_path = Path(result.analysis_path)
        raw = artifact_path.read_bytes()
        artifact_id = "artifact-code-analysis-%s" % uuid.uuid4().hex
        artifact_ref = "artifact:%s" % artifact_id
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            kind="CODE_ANALYSIS_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name="code-analysis.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            attempt_id=lease_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id, "classification:%s" % result.classification],
            metadata={"stage": "CODE_ANALYSIS", "authority": "NODE_OBSERVATION_ONLY", "overall_sufficiency": result.overall_sufficiency},
        )
        self.agent.upload_artifact_file(manifest, str(artifact_path), lease_id=lease_id)
        self.agent.append_runtime_event(
            runtime_event(
                event_id="evt-code-analysis-%s" % uuid.uuid4().hex,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=self.agent.identity.node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref=self.producer_ref,
                event_type="ATTEMPT_COMPLETED",
                sequence=self._next_sequence(test_run_id),
                attempt_id=lease_id,
                refs=list(refs),
                data={"stage_instance_id": stage_instance_id, "evidence_refs": [artifact_ref], "classification": result.classification, "authority": "NODE_OBSERVATION_ONLY"},
            ),
            lease_id=lease_id,
        )
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "artifact_ref": artifact_ref, "classification": result.classification, "overall_sufficiency": result.overall_sufficiency, "terminal": terminal}

    def _next_sequence(self, test_run_id: str) -> int:
        payload = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        value = payload.get("next_sequence")
        if not isinstance(value, int) or value < 0:
            raise CodeAnalysisWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return value

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise CodeAnalysisWorkerError(error)
        return normalized
