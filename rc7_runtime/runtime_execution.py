"""RC7 runtime-owned formal execution bridge.

Execution is deliberately not a DSH/model decision.  This module imports one
strict PASS Script qualification, re-verifies its R1 truth, exact spec/source
bindings and readiness, then lets the runtime issue an L1..L7 execution
identity/lease and launch the approved runner process itself.

A model-authored PASS, exit code, actual result, timeout result or tool-call list
is never accepted here.  Process stdout/stderr are persisted as real files so
Execution/Diagnosis/Defect evidence remains inspectable after the worker/session
that produced the script has disappeared.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from rc6_runtime.automation import (
    JUnitRunnerAdapter,
    ProcessStepResult,
    PytestRunnerAdapter,
    ScriptArtifact,
    ScriptValidation,
)
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableTestSpec
from rc6_runtime.execution import ExecutionProfileRegistry, ExecutionRecord, ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime

from .authority import RC7AuthorityRuntime
from .candidate_payload import CandidatePayloadReader
from .script_validation import EvidenceBackedScriptReadinessValidator


class RuntimeExecutionError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    body = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(body).hexdigest()[:20])


def _file_path(ref: str, code: str) -> Path:
    if not isinstance(ref, str) or not ref.startswith("file://"):
        raise RuntimeExecutionError(code)
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise RuntimeExecutionError(code)
    return path


def _tuple_text(value: object, code: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise RuntimeExecutionError(code)
    return tuple(value)


def _tuple_dict(value: object, code: str) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, dict) for item in value):
        raise RuntimeExecutionError(code)
    return tuple(deepcopy(item) for item in value)


def _spec_from_payload(raw: object) -> ExecutableTestSpec:
    if not isinstance(raw, dict):
        raise RuntimeExecutionError("EXECUTION_SPEC_OBJECT_REQUIRED")
    required_text = (
        "spec_id", "tc_id", "case_fingerprint", "oracle_fingerprint", "release_id",
        "requirement_id", "layer", "runner_type",
    )
    for name in required_text:
        if not isinstance(raw.get(name), str) or not str(raw[name]).strip():
            raise RuntimeExecutionError("EXECUTION_SPEC_FIELD_REQUIRED:%s" % name)
    version = raw.get("case_version")
    if not isinstance(version, int) or version < 1:
        raise RuntimeExecutionError("EXECUTION_SPEC_CASE_VERSION_INVALID")
    cleanup = raw.get("cleanup_policy")
    automation = raw.get("automation_mapping")
    if not isinstance(cleanup, dict) or not isinstance(automation, dict):
        raise RuntimeExecutionError("EXECUTION_SPEC_MAPPING_INVALID")
    sst_id = raw.get("sst_id")
    if sst_id is not None and (not isinstance(sst_id, str) or not sst_id.strip()):
        raise RuntimeExecutionError("EXECUTION_SPEC_SST_ID_INVALID")
    return ExecutableTestSpec(
        spec_id=str(raw["spec_id"]),
        tc_id=str(raw["tc_id"]),
        case_version=version,
        case_fingerprint=str(raw["case_fingerprint"]),
        oracle_fingerprint=str(raw["oracle_fingerprint"]),
        release_id=str(raw["release_id"]),
        requirement_id=str(raw["requirement_id"]),
        sst_id=sst_id,
        layer=str(raw["layer"]).upper(),
        target_requirements=_tuple_text(raw.get("target_requirements"), "EXECUTION_SPEC_TARGET_REQUIREMENTS_INVALID"),
        preconditions=_tuple_dict(raw.get("preconditions"), "EXECUTION_SPEC_PRECONDITIONS_INVALID"),
        test_data_refs=_tuple_text(raw.get("test_data_refs", []), "EXECUTION_SPEC_TEST_DATA_REFS_INVALID"),
        ordered_actions=_tuple_dict(raw.get("ordered_actions"), "EXECUTION_SPEC_ORDERED_ACTIONS_INVALID"),
        oracle_refs=_tuple_text(raw.get("oracle_refs"), "EXECUTION_SPEC_ORACLE_REFS_INVALID"),
        evidence_requirements=_tuple_text(raw.get("evidence_requirements"), "EXECUTION_SPEC_EVIDENCE_REQUIREMENTS_INVALID"),
        cleanup_policy=deepcopy(cleanup),
        runner_type=str(raw["runner_type"]).upper(),
        automation_mapping=deepcopy(automation),
        status=str(raw.get("status") or "EXECUTABLE_SPEC"),
    )


@dataclass(frozen=True)
class VerifiedScriptExecutionBundle:
    upstream_mission_id: str
    upstream_task_id: str
    upstream_evaluation_id: str
    upstream_result_ref: str
    spec_ref: str
    frozen_case: Dict[str, Any]
    spec: ExecutableTestSpec
    script: ScriptArtifact
    validation: ScriptValidation
    source_sha256: str


class StrictScriptExecutionBundleLoader:
    """Rehydrate only a strict, durable SCRIPT_READY result for formal execution."""

    def __init__(self, *, evidence_root: str, validation_timeout_seconds: int = 180) -> None:
        self.evidence_root = Path(evidence_root).resolve()
        self.timeout_seconds = int(validation_timeout_seconds)
        self.reader = CandidatePayloadReader()

    def load(
        self,
        script_result: str,
        *,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> VerifiedScriptExecutionBundle:
        result_path = Path(script_result).expanduser().resolve()
        if not result_path.is_file():
            raise RuntimeExecutionError("SCRIPT_RESULT_NOT_FOUND")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeExecutionError("SCRIPT_RESULT_JSON_INVALID") from exc
        if not isinstance(result, dict):
            raise RuntimeExecutionError("SCRIPT_RESULT_NOT_OBJECT")
        if result.get("status") != "PASS" or result.get("evaluation_result") != "PASS":
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_NOT_PASS")
        if result.get("task_state") != "PASS" or result.get("validation_status") != "SCRIPT_READY":
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_NOT_READY")

        mission_id = result.get("mission_id")
        task_id = result.get("task_id")
        evaluation_id = result.get("evaluation_id")
        for name, value in (("MISSION", mission_id), ("TASK", task_id), ("EVALUATION", evaluation_id)):
            if not isinstance(value, str) or not value:
                raise RuntimeExecutionError("UPSTREAM_SCRIPT_%s_ID_REQUIRED" % name)

        state_root = result_path.parent.parent
        truth = TruthRuntime(state_root / "r1.jsonl")
        tasks = truth.query("rc7_task", task_id=task_id)
        if len(tasks) != 1 or tasks[0].get("mission_id") != mission_id or tasks[0].get("state") != "PASS":
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_TASK_TRUTH_NOT_PASS")
        if tasks[0].get("evaluation_id") != evaluation_id:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_TASK_EVALUATION_MISMATCH")
        evaluations = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
        if len(evaluations) != 1:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_EVALUATION_NOT_UNIQUE")
        evaluation = evaluations[0]
        if evaluation.get("mission_id") != mission_id or evaluation.get("node") != "SCRIPT_READINESS" or evaluation.get("result") != "PASS":
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_EVALUATION_NOT_PASS")
        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, dict):
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_EVALUATION_DIMENSIONS_INVALID")
        if dimensions.get("gate_status") != "SCRIPT_READY" or dimensions.get("business_assertion_executed") is not False:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_GATE_NOT_STRICT_READY")

        spec_path = _file_path(str(result.get("spec_ref") or ""), "UPSTREAM_SCRIPT_SPEC_FILE_REQUIRED")
        try:
            contract = json.loads(spec_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SPEC_JSON_INVALID") from exc
        if not isinstance(contract, dict) or not isinstance(contract.get("frozen_case"), dict):
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_FROZEN_CASE_REQUIRED")
        spec = _spec_from_payload(contract.get("spec"))
        frozen_case = deepcopy(contract["frozen_case"])
        if result.get("spec_id") != spec.spec_id or result.get("tc_id") != spec.tc_id:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SPEC_IDENTITY_MISMATCH")
        if result.get("case_fingerprint") != spec.case_fingerprint or result.get("oracle_fingerprint") != spec.oracle_fingerprint:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_FINGERPRINT_MISMATCH")
        if str(result.get("runner_type") or "").upper() != spec.runner_type:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_RUNNER_MISMATCH")

        output_refs = tasks[0].get("output_artifact_refs")
        if not isinstance(output_refs, list) or len(output_refs) != 1:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_CANDIDATE_ARTIFACT_REQUIRED")
        candidate = self.reader.load(
            truth,
            str(output_refs[0]),
            expected_mission_id=mission_id,
            expected_task_id=task_id,
        )
        semantic = candidate.semantic_payload
        binding = semantic.get("binding")
        if not isinstance(binding, dict):
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_BINDING_REQUIRED")
        expected_binding = {
            "spec_id": spec.spec_id,
            "tc_id": spec.tc_id,
            "case_version": spec.case_version,
            "runner_type": spec.runner_type,
            "case_fingerprint": spec.case_fingerprint,
            "oracle_fingerprint": spec.oracle_fingerprint,
            "design_content_hash": contract.get("design_content_hash"),
        }
        for key, value in expected_binding.items():
            if binding.get(key) != value:
                raise RuntimeExecutionError("UPSTREAM_SCRIPT_BINDING_MISMATCH:%s" % key)
        source_text = semantic.get("source_text")
        test_symbol = semantic.get("test_symbol")
        if not isinstance(source_text, str) or not source_text.strip() or not isinstance(test_symbol, str) or not test_symbol.strip():
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SOURCE_OR_SYMBOL_MISSING")

        source_path = _file_path(str(result.get("source_ref") or ""), "UPSTREAM_SCRIPT_SOURCE_FILE_REQUIRED")
        source_bytes = source_path.read_bytes()
        try:
            persisted_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SOURCE_NOT_UTF8") from exc
        if persisted_text != source_text:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SOURCE_DRIFT")
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        source_evidence = [
            row for row in truth.query("rc7_evidence")
            if row.get("mission_id") == mission_id
            and row.get("kind") == "RUNTIME_PERSISTED_SCRIPT_SOURCE"
            and row.get("content_ref") == "file://" + str(source_path)
        ]
        if len(source_evidence) != 1 or source_evidence[0].get("content_hash") != "sha256:" + source_digest:
            raise RuntimeExecutionError("UPSTREAM_SCRIPT_SOURCE_R1_HASH_PROOF_MISSING")

        artifact_rows = truth.query("rc7_artifact", artifact_id=str(output_refs[0]))
        candidate_evidence = artifact_rows[0].get("evidence_refs", []) if len(artifact_rows) == 1 else []
        builder_evidence = tuple(dict.fromkeys(
            [str(ref) for ref in candidate_evidence if isinstance(ref, str) and ref]
            + [str(source_evidence[0]["evidence_id"])]
        ))
        reuse_refs = []
        reuse = spec.automation_mapping.get("reuse", {})
        if isinstance(reuse, dict):
            for values in reuse.values():
                if isinstance(values, list):
                    reuse_refs.extend(value for value in values if isinstance(value, str) and value)
        script_id = _stable_id(
            "SCRIPT-RC7", mission_id, spec.spec_id, source_digest, test_symbol.strip()
        )
        script = ScriptArtifact(
            script_id=script_id,
            spec_id=spec.spec_id,
            tc_id=spec.tc_id,
            case_version=spec.case_version,
            layer=spec.layer,
            runner_type=spec.runner_type,
            source_ref="file://" + str(source_path),
            test_symbol=test_symbol.strip(),
            case_fingerprint=spec.case_fingerprint,
            oracle_fingerprint=spec.oracle_fingerprint,
            reuse_refs=tuple(dict.fromkeys(reuse_refs)),
            builder_evidence_refs=builder_evidence,
            revision=1,
        )

        validation = EvidenceBackedScriptReadinessValidator(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
        ).validate(spec=spec, script=script, cwd=cwd, env=env)
        if not validation.ready:
            raise RuntimeExecutionError("SCRIPT_REVALIDATION_NOT_READY")
        return VerifiedScriptExecutionBundle(
            upstream_mission_id=mission_id,
            upstream_task_id=task_id,
            upstream_evaluation_id=evaluation_id,
            upstream_result_ref="file://" + str(result_path),
            spec_ref="file://" + str(spec_path),
            frozen_case=frozen_case,
            spec=spec,
            script=script,
            validation=validation,
            source_sha256=source_digest,
        )


class _EvidenceBackedProcessHarness:
    """Drop-in RunnerAdapter harness that persists process output bytes."""

    def __init__(self, *, evidence_root: str, timeout_seconds: int) -> None:
        self.root = Path(evidence_root).resolve()
        self.timeout_seconds = int(timeout_seconds)

    def run(self, name: str, command: Tuple[str, ...], cwd: str, env: Optional[Mapping[str, str]] = None) -> ProcessStepResult:
        run_id = "EXECRUN-" + uuid.uuid4().hex
        folder = self.root / "formal-execution" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        stdout = ""
        stderr = ""
        code = 1
        started = time.monotonic()
        merged = os.environ.copy()
        if env:
            merged.update({str(key): str(value) for key, value in env.items()})
        try:
            completed = subprocess.run(
                list(command), cwd=cwd, env=merged,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=self.timeout_seconds, check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            code = int(completed.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stderr += "\nPROCESS_TIMEOUT"
            code = 124
        except OSError as exc:
            stderr = "%s:%s" % (type(exc).__name__, exc)
            code = 127
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout_path = folder / "stdout.log"
        stderr_path = folder / "stderr.log"
        command_path = folder / "command.json"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        command_path.write_text(
            json.dumps({
                "name": name,
                "command": list(command),
                "cwd": str(Path(cwd).resolve()),
                "exit_code": code,
                "duration_ms": duration_ms,
            }, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return ProcessStepResult(
            name=name,
            command=tuple(str(item) for item in command),
            exit_code=code,
            stdout_ref="file://" + str(stdout_path),
            stderr_ref="file://" + str(stderr_path),
            duration_ms=duration_ms,
            passed=(code == 0),
        )


@dataclass(frozen=True)
class RuntimeOwnedExecutionResult:
    record: ExecutionRecord
    runtime_worker_id: str
    runtime_lease_id: str
    runner_type: str


class RuntimeOwnedExecutionCoordinator:
    """Issue execution authority and run the approved Script without model control."""

    def __init__(self, *, evidence_root: str, timeout_seconds: int = 300) -> None:
        self.evidence_root = str(Path(evidence_root).resolve())
        self.timeout_seconds = int(timeout_seconds)
        self.profiles = ExecutionProfileRegistry()

    def execute(
        self,
        *,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> RuntimeOwnedExecutionResult:
        if prepared.tc_id != bundle.spec.tc_id or prepared.case_version != bundle.spec.case_version:
            raise RuntimeExecutionError("PREPARED_ATTEMPT_SCRIPT_CASE_MISMATCH")
        if prepared.status != "PREPARED":
            raise RuntimeExecutionError("FORMAL_EXECUTION_REQUIRES_PREPARED_ATTEMPT")
        profile = self.profiles.get(bundle.spec.layer)
        identity = authority.issue_identity(
            profile.role,
            "EXECUTION",
            profile.layer,
            0,
            "runtime-execution-" + uuid.uuid4().hex,
        )
        lease = authority.issue_lease(
            identity.worker_id,
            "case:%s@%s" % (bundle.spec.tc_id, bundle.spec.case_version),
            ExecutionRuntime.REQUIRED_ARTIFACTS,
            profile.required_tools,
            ttl_seconds=max(self.timeout_seconds + 120, 300),
        )

        if bundle.spec.runner_type == "PYTEST":
            runner = PytestRunnerAdapter(timeout_seconds=self.timeout_seconds)
        elif bundle.spec.runner_type == "JUNIT":
            runner = JUnitRunnerAdapter(timeout_seconds=self.timeout_seconds)
        else:
            raise RuntimeExecutionError("FORMAL_RUNNER_NOT_IMPLEMENTED:%s" % bundle.spec.runner_type)
        runner.harness = _EvidenceBackedProcessHarness(
            evidence_root=self.evidence_root,
            timeout_seconds=self.timeout_seconds,
        )
        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
        )
        record = runtime.execute_with_runner(
            case=deepcopy(bundle.frozen_case),
            executable_spec=bundle.spec,
            script=bundle.script,
            validation=bundle.validation,
            prepared=prepared,
            worker_id=identity.worker_id,
            lease_id=lease.lease_id,
            runner=runner,
            cwd=cwd,
            env=env,
        )
        return RuntimeOwnedExecutionResult(
            record=record,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
            runner_type=bundle.spec.runner_type,
        )
