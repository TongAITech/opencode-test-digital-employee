"""RC8 REQUIREMENT_ANALYSIS worker bound to frozen business revisions.

The worker consumes only a Center-claimed REQUIREMENT_ANALYSIS WorkItem. It
never guesses requirement/system versions. Immutable ``requirement-revision:``
and ``scope-revision:`` refs must already be present on the WorkItem, and source
material refs must come from those Revision payloads.

All runtime truth is published through FormalNodeAgent -> Center -> RC8 R1.
DSH execution itself is truth-neutral via DshJsonRunner.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

from .dsh_json_runner import DshJsonResult, DshJsonRunner, DshJsonRunnerError


class RequirementAnalysisWorkerError(RuntimeError):
    pass


_REQUIRED_LIST_FIELDS = (
    "source_assertions",
    "atomic_statements",
    "trace_links",
    "evidence_refs",
    "business_rules",
    "roles",
    "preconditions",
    "normal_paths",
    "negative_paths",
    "boundaries",
    "states",
    "data_constraints",
    "dependencies",
    "side_effects",
)


class RequirementAnalysisWorker:
    producer_ref = "RC8_REQUIREMENT_ANALYSIS_WORKER"

    def __init__(
        self,
        *,
        agent: Any,
        dsh_runner: DshJsonRunner,
        work_dir: str,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict):
            raise RequirementAnalysisWorkerError("CLAIMED_WORK_ITEM_REQUIRED")
        identity = work.get("identity")
        if not isinstance(identity, dict):
            raise RequirementAnalysisWorkerError("WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "REQUIREMENT_ANALYSIS":
            raise RequirementAnalysisWorkerError("WORK_ITEM_STAGE_NOT_REQUIREMENT_ANALYSIS")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(
            getattr(claimed, "stage_instance_id", None),
            "STAGE_INSTANCE_ID_REQUIRED",
        )
        scope_refs = tuple(str(value).strip() for value in identity.get("scope_refs") or [] if str(value).strip())
        requirement_revision_id = self._one_ref(scope_refs, "requirement-revision:")
        scope_revision_id = self._one_ref(scope_refs, "scope-revision:")

        requirement_revision = self.agent.center.get(
            "/api/v1/requirement-revisions/%s" % quote(requirement_revision_id, safe="")
        )
        scope_revision = self.agent.center.get(
            "/api/v1/scope-revisions/%s" % quote(scope_revision_id, safe="")
        )
        if str(scope_revision.get("requirement_revision_id") or "") != requirement_revision_id:
            raise RequirementAnalysisWorkerError("SCOPE_REVISION_REQUIREMENT_MISMATCH")
        source_refs = self._revision_source_refs(requirement_revision, scope_revision)
        input_snapshot_ref = "requirement-revision:%s|scope-revision:%s" % (
            requirement_revision_id,
            scope_revision_id,
        )
        attempt_id = "att-req-%s" % uuid.uuid4().hex

        self.agent.start(work_item_id, lease_id=lease_id)
        started_sequence = self._next_sequence(test_run_id)
        self.agent.append_runtime_event(
            runtime_event(
                event_id="evt-req-start-%s" % uuid.uuid4().hex,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=self.agent.identity.node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref=self.producer_ref,
                event_type="ATTEMPT_STARTED",
                sequence=started_sequence,
                attempt_id=attempt_id,
                refs=list(scope_refs),
                data={
                    "stage_instance_id": stage_instance_id,
                    "input_snapshot_ref": input_snapshot_ref,
                    "started_at": self._now(),
                },
            ),
            lease_id=lease_id,
        )

        if not source_refs:
            return self._terminal_failure(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                stage_instance_id=stage_instance_id,
                lease_id=lease_id,
                attempt_id=attempt_id,
                input_snapshot_ref=input_snapshot_ref,
                scope_refs=scope_refs,
                event_type="ATTEMPT_BLOCKED",
                failure_ownership="DEPENDENCY",
                reason="REQUIREMENT_REVISION_SOURCE_REFS_REQUIRED",
                detail={
                    "requirement_revision_id": requirement_revision_id,
                    "scope_revision_id": scope_revision_id,
                },
            )

        prompt = self._prompt(
            requirement_revision_id=requirement_revision_id,
            scope_revision_id=scope_revision_id,
            source_refs=source_refs,
        )
        try:
            result = self.dsh_runner.run(prompt)
            candidate = self._validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            return self._terminal_failure(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                stage_instance_id=stage_instance_id,
                lease_id=lease_id,
                attempt_id=attempt_id,
                input_snapshot_ref=input_snapshot_ref,
                scope_refs=scope_refs,
                event_type="ATTEMPT_FAILED_RUNTIME",
                failure_ownership=self._failure_ownership(exc.reason),
                reason=exc.reason,
                detail={
                    "exit_code": exc.exit_code,
                    "stdout_tail": exc.stdout[-12000:],
                    "stderr_tail": exc.stderr[-12000:],
                },
            )
        except RequirementAnalysisWorkerError as exc:
            return self._terminal_failure(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                stage_instance_id=stage_instance_id,
                lease_id=lease_id,
                attempt_id=attempt_id,
                input_snapshot_ref=input_snapshot_ref,
                scope_refs=scope_refs,
                event_type="ATTEMPT_FAILED_RUNTIME",
                failure_ownership="MODEL",
                reason=str(exc),
                detail={},
            )

        artifact = {
            "schema_version": "rc8.requirement-analysis.v1",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "requirement_revision_id": requirement_revision_id,
            "scope_revision_id": scope_revision_id,
            "source_refs": list(source_refs),
            "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls),
            "candidate": candidate,
            "generated_at": self._now(),
        }
        artifact_id = "artifact-req-analysis-%s" % uuid.uuid4().hex
        artifact_ref = self._upload_json_artifact(
            artifact_id=artifact_id,
            kind="REQUIREMENT_ANALYSIS",
            file_name="requirement-analysis.json",
            content=artifact,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            stage_instance_id=stage_instance_id,
            attempt_id=attempt_id,
            lease_id=lease_id,
            refs=list(scope_refs) + list(source_refs),
        )
        finished_sequence = self._next_sequence(test_run_id)
        self.agent.append_runtime_event(
            runtime_event(
                event_id="evt-req-complete-%s" % uuid.uuid4().hex,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=self.agent.identity.node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref=self.producer_ref,
                event_type="ATTEMPT_COMPLETED",
                sequence=finished_sequence,
                attempt_id=attempt_id,
                refs=list(scope_refs),
                data={
                    "stage_instance_id": stage_instance_id,
                    "input_snapshot_ref": input_snapshot_ref,
                    "action_refs": [str(item.get("call_ref") or "") for item in result.tool_calls if item.get("call_ref")],
                    "evidence_refs": [artifact_ref],
                    "finished_at": self._now(),
                },
            ),
            lease_id=lease_id,
        )
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {
            "status": "COMPLETED",
            "attempt_id": attempt_id,
            "artifact_ref": artifact_ref,
            "dsh_session_id": result.session_id,
            "terminal": terminal,
        }

    def _terminal_failure(
        self,
        *,
        test_run_id: str,
        work_item_id: str,
        stage_instance_id: str,
        lease_id: str,
        attempt_id: str,
        input_snapshot_ref: str,
        scope_refs: Sequence[str],
        event_type: str,
        failure_ownership: str,
        reason: str,
        detail: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "schema_version": "rc8.requirement-analysis-failure.v1",
            "reason": reason,
            "failure_ownership": failure_ownership,
            "detail": detail,
            "attempt_id": attempt_id,
            "stage_instance_id": stage_instance_id,
            "recorded_at": self._now(),
        }
        artifact_id = "artifact-req-failure-%s" % uuid.uuid4().hex
        artifact_ref = self._upload_json_artifact(
            artifact_id=artifact_id,
            kind="REQUIREMENT_ANALYSIS_FAILURE",
            file_name="requirement-analysis-failure.json",
            content=payload,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            stage_instance_id=stage_instance_id,
            attempt_id=attempt_id,
            lease_id=lease_id,
            refs=list(scope_refs),
        )
        sequence = self._next_sequence(test_run_id)
        self.agent.append_runtime_event(
            runtime_event(
                event_id="evt-req-terminal-%s" % uuid.uuid4().hex,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=self.agent.identity.node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref=self.producer_ref,
                event_type=event_type,
                sequence=sequence,
                attempt_id=attempt_id,
                refs=list(scope_refs),
                data={
                    "stage_instance_id": stage_instance_id,
                    "input_snapshot_ref": input_snapshot_ref,
                    "evidence_refs": [artifact_ref],
                    "failure_ownership": failure_ownership,
                    "finished_at": self._now(),
                },
            ),
            lease_id=lease_id,
        )
        terminal = self.agent.fail(work_item_id, lease_id=lease_id)
        return {
            "status": "BLOCKED" if event_type == "ATTEMPT_BLOCKED" else "FAILED_RUNTIME",
            "attempt_id": attempt_id,
            "artifact_ref": artifact_ref,
            "reason": reason,
            "terminal": terminal,
        }

    def _upload_json_artifact(
        self,
        *,
        artifact_id: str,
        kind: str,
        file_name: str,
        content: Dict[str, Any],
        test_run_id: str,
        work_item_id: str,
        stage_instance_id: str,
        attempt_id: str,
        lease_id: str,
        refs: Sequence[str],
    ) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            kind=kind,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name=file_name,
            sha256=digest,
            size_bytes=len(raw),
            attempt_id=attempt_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "REQUIREMENT_ANALYSIS"},
            created_at=self._now(),
        )
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get(
            "/api/v1/test-runs/%s/nodes/%s/runtime-sequence"
            % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe=""))
        )
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise RequirementAnalysisWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _one_ref(scope_refs: Sequence[str], prefix: str) -> str:
        values = [value[len(prefix):] for value in scope_refs if value.startswith(prefix) and value[len(prefix):]]
        if len(values) != 1:
            raise RequirementAnalysisWorkerError("%sREF_REQUIRED_EXACTLY_ONCE" % prefix.upper().replace("-", "_").replace(":", "_"))
        return values[0]

    @staticmethod
    def _revision_source_refs(requirement_revision: Dict[str, Any], scope_revision: Dict[str, Any]) -> Tuple[str, ...]:
        found: List[str] = []
        for revision in (requirement_revision, scope_revision):
            payload = revision.get("payload")
            if not isinstance(payload, dict):
                continue
            values = payload.get("source_refs")
            if values is None:
                continue
            if not isinstance(values, list):
                raise RequirementAnalysisWorkerError("REVISION_SOURCE_REFS_MUST_BE_LIST")
            for value in values:
                normalized = str(value or "").strip()
                if normalized:
                    found.append(normalized)
        return tuple(dict.fromkeys(found))

    @staticmethod
    def _validate_candidate(value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_OUTPUT_OBJECT_REQUIRED")
        for field in _REQUIRED_LIST_FIELDS:
            if field not in value or not isinstance(value[field], list):
                raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_%s_LIST_REQUIRED" % field.upper())
        for field in ("atomic_statements", "trace_links", "evidence_refs"):
            if not value[field]:
                raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_%s_NONEMPTY_REQUIRED" % field.upper())
        evidence = {str(item).strip() for item in value["evidence_refs"] if str(item).strip()}
        if not evidence:
            raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        for link in value["trace_links"]:
            if not isinstance(link, dict):
                raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_TRACE_LINK_OBJECT_REQUIRED")
            evidence_ref = str(link.get("evidence_ref") or "").strip()
            if not evidence_ref or evidence_ref not in evidence:
                raise RequirementAnalysisWorkerError("REQUIREMENT_ANALYSIS_TRACE_EVIDENCE_MISMATCH")
        return dict(value)

    @staticmethod
    def _failure_ownership(reason: str) -> str:
        token = str(reason or "").split(":", 1)[0]
        if token in {"DSH_NOT_AVAILABLE", "DSH_LAUNCH_FAILED"}:
            return "TOOL"
        if token in {"DSH_TIMEOUT", "DSH_SESSION_ID_MISSING", "WORKER_SESSION_NOT_INDEPENDENT"}:
            return "SESSION_RUNTIME"
        return "MODEL"

    @staticmethod
    def _prompt(*, requirement_revision_id: str, scope_revision_id: str, source_refs: Sequence[str]) -> str:
        return (
            "You are the RC8 REQUIREMENT_ANALYSIS worker. Do not decide PASS or sufficiency. "
            "Analyze only RequirementRevision %s and ScopeRevision %s. "
            "Use real tools to inspect only these revision-declared source refs: %s. "
            "Do not guess missing content, system versions, APIs or historical requirements. "
            "Return one strict JSON object with exactly these list fields: %s. "
            "atomic_statements, trace_links and evidence_refs must be non-empty. "
            "Each trace_links item must be an object whose evidence_ref exists in evidence_refs. "
            "Keep source excerpts compact; evidence refs should point to the actual inspected source/tool results."
            % (
                requirement_revision_id,
                scope_revision_id,
                json.dumps(list(source_refs), ensure_ascii=False),
                ", ".join(_REQUIRED_LIST_FIELDS),
            )
        )

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise RequirementAnalysisWorkerError(error)
        return normalized
