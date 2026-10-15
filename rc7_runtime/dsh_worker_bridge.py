"""RC7 bridge from durable READY Tasks to independent DSH headless workers.

The bridge owns no testing judgment. A successful DSH process and a successful
worker handoff produce only a candidate Task output (OUTPUT_PRODUCED). An
independent node evaluator remains the sole authority that may accept it.

The bridge is session-independent: prompts are compiled entirely from durable
Task/Mission references and never contain coordinator conversation history.
Worker-declared content references, hashes and evidence ids are not trusted as
canonical storage: the normalized candidate envelope is atomically persisted
and hashed by Runtime, and the Artifact references only Runtime-created
Evidence ids.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerAssignment, WorkerInvocation

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .mission_graph import MissionTaskGraphCompiler
from .models import Artifact, Evidence, Task, TaskStatus


class DshWorkerBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DshNodePolicy:
    agent_id: str
    role: str
    phase: str
    allowed_artifact_types: Tuple[str, ...]
    allowed_tools: Tuple[str, ...]


@dataclass(frozen=True)
class DshTaskRunResult:
    task_id: str
    worker_instance_id: str
    dsh_session_id: str
    tool_call_count: int
    raw_output_ref: str
    output_artifact_ids: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    task_state: str


DEFAULT_NODE_POLICIES: Mapping[str, DshNodePolicy] = {
    "REQUIREMENT_ANALYSIS": DshNodePolicy(
        agent_id="requirement-analysis",
        role="RC7_REQUIREMENT_WORKER",
        phase="ANALYSIS",
        allowed_artifact_types=("rc7_requirement_candidate",),
        allowed_tools=("filesystem",),
    ),
    "CODE_ANALYSIS": DshNodePolicy(
        agent_id="code-analysis",
        role="RC7_CODE_WORKER",
        phase="ANALYSIS",
        allowed_artifact_types=("rc7_code_candidate",),
        allowed_tools=("git", "codegraph"),
    ),
    "TEST_DESIGN": DshNodePolicy(
        agent_id="test-design",
        role="RC7_TEST_DESIGN_WORKER",
        phase="DESIGN",
        allowed_artifact_types=("rc7_test_design_candidate",),
        allowed_tools=("codegraph", "filesystem"),
    ),
    "SCRIPT_READINESS": DshNodePolicy(
        agent_id="test-automation",
        role="RC7_SCRIPT_WORKER",
        phase="AUTOMATION",
        allowed_artifact_types=("rc7_script_candidate",),
        allowed_tools=("filesystem", "pytest", "junit"),
    ),
    "EXECUTION": DshNodePolicy(
        agent_id="test-execution",
        role="RC7_EXECUTION_WORKER",
        phase="EXECUTION",
        allowed_artifact_types=("rc7_execution_candidate",),
        allowed_tools=("api", "browser", "database", "cat"),
    ),
    "DEFECT": DshNodePolicy(
        agent_id="defect-analysis",
        role="RC7_DEFECT_WORKER",
        phase="DIAGNOSIS",
        allowed_artifact_types=("rc7_defect_candidate",),
        allowed_tools=("git", "codegraph", "cat"),
    ),
    "RUNTIME": DshNodePolicy(
        agent_id="runtime-recovery",
        role="RC7_RUNTIME_RECOVERY_WORKER",
        phase="RECOVERY",
        allowed_artifact_types=("rc7_runtime_candidate",),
        allowed_tools=("filesystem",),
    ),
}


_SEMANTIC_PAYLOAD_HINTS = {
    "REQUIREMENT_ANALYSIS": (
        "source_assertions, atomic_statements, trace_links, evidence_refs, business_rules, roles, "
        "preconditions, normal_paths, negative_paths, boundaries, states, data_constraints, "
        "dependencies, side_effects"
    ),
    "CODE_ANALYSIS": (
        "requirement_ids, source_revisions, changed_files, changed_symbols, symbol_explanations, "
        "reverse_requirement_mappings, tool_calls, evidence_refs, codegraph_required"
    ),
    "TEST_DESIGN": "obligations and test cases with coverage links, risk, action semantics and oracles",
    "SCRIPT_READINESS": "test case, execution contract, executable script metadata and validation evidence",
    "EXECUTION": "execution record, actual result, assertion outcome, tool calls and evidence references",
    "DEFECT": "defect qualification/RCA/fix verification/regression evidence without declaring Mission completion",
    "RUNTIME": "recovery action and evidence proving the runtime prerequisite was restored",
}


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class DshTaskWorkerBridge:
    def __init__(
        self,
        control: ClosedLoopControlPlane,
        launcher: DshHeadlessWorkerLauncher,
        *,
        node_policies: Optional[Mapping[str, DshNodePolicy]] = None,
    ) -> None:
        self.control = control
        self.launcher = launcher
        self.node_policies = dict(node_policies or DEFAULT_NODE_POLICIES)
        self.graph_compiler = MissionTaskGraphCompiler()

    def run_next(self) -> Optional[DshTaskRunResult]:
        ready = self.control.scheduler.ready_tasks(self.control.mission_id)
        if not ready:
            return None

        chosen = next((task for task in ready if task.node in self.node_policies), None)
        if chosen is None:
            raise DshWorkerBridgeError("READY_TASK_HAS_NO_DSH_POLICY")
        policy = self.node_policies[chosen.node]
        assignment = self._assign(chosen, policy)

        leased = self.control.lease_next(
            worker_ref=assignment.worker_instance_id,
            capabilities=chosen.required_capabilities,
        )
        if leased is None or leased.task_id != chosen.task_id:
            raise DshWorkerBridgeError("DSH_ASSIGNMENT_TASK_LEASE_MISMATCH")
        running = self.control.start(chosen.task_id, worker_ref=assignment.worker_instance_id)

        prompt = self.compile_prompt(running, assignment)
        invocation, raw_output = self.launcher.execute(assignment, prompt)
        worker_output = self.normalize_output(running, invocation, raw_output)
        candidate = self.control.submit_worker_output(worker_output)
        if candidate.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshWorkerBridgeError("DSH_WORKER_MUST_STOP_AT_OUTPUT_PRODUCED")

        raw_output_ref = next(
            (ref for ref in invocation.evidence_refs if ref.startswith("file://")),
            "",
        )
        return DshTaskRunResult(
            task_id=running.task_id,
            worker_instance_id=assignment.worker_instance_id,
            dsh_session_id=invocation.dsh_session_id or "",
            tool_call_count=len(invocation.tool_calls),
            raw_output_ref=raw_output_ref,
            output_artifact_ids=tuple(candidate.output_artifact_refs),
            evidence_ids=tuple(item.evidence_id for item in worker_output.evidence),
            task_state=candidate.state.value,
        )

    def compile_prompt(self, task: Task, assignment: WorkerAssignment) -> str:
        expected_id, expected_type = self.expected_output(task)
        contract = {
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "task_type": task.task_type,
            "objective": task.objective,
            "scope": assignment.scope,
            "input_artifact_refs": list(task.input_artifact_refs),
            "gap_refs": list(task.gap_refs),
            "acceptance_criteria": list(task.acceptance_criteria),
            "required_capabilities": list(task.required_capabilities),
            "allowed_tools": list(assignment.allowed_tools),
            "expected_output": {
                "artifact_id": expected_id,
                "artifact_type": expected_type,
            },
        }
        schema = {
            "task_id": task.task_id,
            "artifact": {
                "artifact_id": expected_id,
                "artifact_type": expected_type,
                "content_ref": "worker-declared source reference; runtime will persist canonical payload",
                "parent_refs": "list[str] containing every required input_artifact_ref",
                "evidence_refs": "optional worker aliases for audit only; Runtime will store canonical Evidence ids",
            },
            "semantic_payload": {
                "type": "non-empty object",
                "node_guidance": _SEMANTIC_PAYLOAD_HINTS.get(task.node, "evaluator-ready node output"),
            },
            "evidence": [
                {
                    "kind": "non-empty kind",
                    "source_ref": "real source/tool reference",
                    "content_ref": "durable evidence reference",
                    "subject_refs": "list[str]",
                    "content_hash": "optional source evidence hash",
                }
            ],
        }
        return (
            "You are an RC7 professional worker executing one leased task. "
            "Do not evaluate or mark the task PASS. Do not return an Evaluation object. "
            "You MUST call at least one allowed real tool; a text-only answer is invalid. "
            "Read/use every input_artifact_ref that is relevant to the task, produce evidence-backed "
            "candidate output, put the professional node result in semantic_payload, and return "
            "exactly one JSON object.\n"
            "TASK_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )

    def normalize_output(
        self,
        task: Task,
        invocation: WorkerInvocation,
        raw_output: Dict[str, Any],
    ) -> WorkerOutput:
        if invocation.mission_id != task.mission_id:
            raise DshWorkerBridgeError("DSH_INVOCATION_MISSION_MISMATCH")
        if invocation.worker_instance_id != task.lease_owner:
            raise DshWorkerBridgeError("DSH_INVOCATION_LEASE_OWNER_MISMATCH")
        if not invocation.dsh_session_id:
            raise DshWorkerBridgeError("DSH_SESSION_EVIDENCE_REQUIRED")
        if not invocation.tool_calls:
            raise DshWorkerBridgeError("DSH_REAL_TOOL_CALL_REQUIRED")
        if raw_output.get("task_id") != task.task_id:
            raise DshWorkerBridgeError("DSH_OUTPUT_TASK_ID_MISMATCH")

        semantic_payload = raw_output.get("semantic_payload")
        if not isinstance(semantic_payload, dict) or not semantic_payload:
            raise DshWorkerBridgeError("DSH_OUTPUT_SEMANTIC_PAYLOAD_REQUIRED")
        if "evaluation" in semantic_payload or "task_state" in semantic_payload:
            raise DshWorkerBridgeError("DSH_WORKER_ACCEPTANCE_FIELDS_FORBIDDEN")

        raw_artifact = raw_output.get("artifact")
        if not isinstance(raw_artifact, dict):
            raise DshWorkerBridgeError("DSH_OUTPUT_ARTIFACT_REQUIRED")
        expected_id, expected_type = self.expected_output(task)
        if raw_artifact.get("artifact_id") != expected_id:
            raise DshWorkerBridgeError("DSH_OUTPUT_ARTIFACT_ID_MISMATCH")
        if raw_artifact.get("artifact_type") != expected_type:
            raise DshWorkerBridgeError("DSH_OUTPUT_ARTIFACT_TYPE_MISMATCH")
        declared_content_ref = raw_artifact.get("content_ref")
        if not isinstance(declared_content_ref, str) or not declared_content_ref.strip():
            raise DshWorkerBridgeError("DSH_OUTPUT_CONTENT_REF_REQUIRED")

        evidence = []
        for ref in invocation.evidence_refs:
            if not isinstance(ref, str) or not ref:
                continue
            evidence.append(
                Evidence(
                    evidence_id=_stable_id(
                        "EVD-DSH",
                        task.mission_id,
                        task.task_id,
                        invocation.worker_instance_id,
                        ref,
                    ),
                    mission_id=task.mission_id,
                    kind="DSH_RUNTIME_PROOF",
                    source_ref="dsh://worker/%s" % invocation.worker_instance_id,
                    content_ref=ref,
                    subject_refs=[task.task_id, invocation.attempt_id],
                )
            )

        raw_evidence = raw_output.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise DshWorkerBridgeError("DSH_OUTPUT_EVIDENCE_REQUIRED")
        for index, item in enumerate(raw_evidence):
            if not isinstance(item, dict):
                raise DshWorkerBridgeError("DSH_OUTPUT_EVIDENCE_SHAPE_INVALID")
            kind = item.get("kind")
            source_ref = item.get("source_ref")
            item_content_ref = item.get("content_ref")
            if not all(isinstance(value, str) and value.strip() for value in (kind, source_ref, item_content_ref)):
                raise DshWorkerBridgeError("DSH_OUTPUT_EVIDENCE_FIELDS_REQUIRED")
            subject_refs = item.get("subject_refs", [task.task_id])
            if not isinstance(subject_refs, list) or not all(isinstance(value, str) and value for value in subject_refs):
                raise DshWorkerBridgeError("DSH_OUTPUT_EVIDENCE_SUBJECT_REFS_INVALID")
            evidence.append(
                Evidence(
                    evidence_id=_stable_id(
                        "EVD-WORKER",
                        task.mission_id,
                        task.task_id,
                        invocation.attempt_id,
                        str(index),
                        item_content_ref,
                    ),
                    mission_id=task.mission_id,
                    kind=kind,
                    source_ref=source_ref,
                    content_ref=item_content_ref,
                    subject_refs=list(subject_refs),
                    content_hash=item.get("content_hash") if isinstance(item.get("content_hash"), str) else None,
                )
            )

        evidence_ids = list(dict.fromkeys(item.evidence_id for item in evidence))
        parent_refs = raw_artifact.get("parent_refs", list(task.input_artifact_refs))
        if not isinstance(parent_refs, list) or not all(isinstance(value, str) and value for value in parent_refs):
            raise DshWorkerBridgeError("DSH_OUTPUT_PARENT_REFS_INVALID")
        if not set(task.input_artifact_refs).issubset(set(parent_refs)):
            raise DshWorkerBridgeError("DSH_OUTPUT_DROPPED_REQUIRED_PARENT")

        artifact_evidence_refs = raw_artifact.get("evidence_refs", [])
        if not isinstance(artifact_evidence_refs, list) or not all(
            isinstance(value, str) and value for value in artifact_evidence_refs
        ):
            raise DshWorkerBridgeError("DSH_OUTPUT_ARTIFACT_EVIDENCE_REFS_INVALID")

        canonical_content_ref, runtime_hash = self._persist_candidate_payload(
            task,
            invocation,
            raw_output,
        )
        existing_artifacts = self.control.truth.query("rc7_artifact", artifact_id=expected_id)
        next_artifact_version = (
            max(int(row.get("version", 0)) for row in existing_artifacts) + 1
            if existing_artifacts
            else 1
        )
        artifact = Artifact(
            artifact_id=expected_id,
            mission_id=task.mission_id,
            artifact_type=expected_type,
            producer_task_id=task.task_id,
            content_ref=canonical_content_ref,
            version=next_artifact_version,
            parent_refs=list(dict.fromkeys(parent_refs)),
            evidence_refs=evidence_ids,
            content_hash=runtime_hash,
        )
        return WorkerOutput(
            task_id=task.task_id,
            worker_ref=invocation.worker_instance_id,
            artifacts=(artifact,),
            evidence=tuple(evidence),
        )

    def expected_output(self, task: Task) -> Tuple[str, str]:
        if task.task_type == "PRODUCE" and task.node in self.graph_compiler.OUTPUT_TYPES:
            graph = self.graph_compiler.compile(task.mission_id)
            return graph.artifact_ids[task.node], self.graph_compiler.OUTPUT_TYPES[task.node]
        artifact_type = "DEFECT_CLOSURE" if task.node == "DEFECT" else "%s_OUTPUT" % task.node
        return _stable_id("ART-TASK", task.mission_id, task.task_id), artifact_type

    def _persist_candidate_payload(
        self,
        task: Task,
        invocation: WorkerInvocation,
        raw_output: Dict[str, Any],
    ) -> Tuple[str, str]:
        launcher_root = getattr(self.launcher, "state_root", None)
        if launcher_root is not None:
            root = Path(launcher_root)
        else:
            store_path = getattr(self.control.truth.store, "path", None)
            root = Path(store_path).parent if store_path is not None else Path.cwd()
        target_dir = root / "rc7-worker-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "candidate",
            task.mission_id,
            task.task_id,
            invocation.attempt_id,
            invocation.worker_instance_id,
        ) + ".json"
        target = target_dir / filename
        serialized = json.dumps(
            raw_output,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        ) + "\n"
        encoded = serialized.encode("utf-8")
        runtime_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
        fd, temp_name = tempfile.mkstemp(prefix=filename + ".", suffix=".tmp", dir=str(target_dir))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return "file://" + str(target.resolve()), runtime_hash

    def _assign(self, task: Task, policy: DshNodePolicy) -> WorkerAssignment:
        task_rows = self.control.truth.query("rc7_task", task_id=task.task_id)
        if len(task_rows) != 1:
            raise DshWorkerBridgeError("DSH_TASK_REVISION_NOT_UNIQUE")
        durable_task_revision = int(task_rows[0].get("artifact_version", 0))
        attempt_id = _stable_id("ATT-DSH", task.mission_id, task.task_id, str(durable_task_revision))
        input_refs = list(task.input_artifact_refs) + ["gap://%s" % gap_id for gap_id in task.gap_refs]
        return self.launcher.assign(
            agent_id=policy.agent_id,
            role=policy.role,
            phase=policy.phase,
            mission_id=task.mission_id,
            attempt_id=attempt_id,
            scope="task:%s" % task.task_id,
            input_refs=input_refs,
            allowed_artifact_types=policy.allowed_artifact_types,
            allowed_tools=policy.allowed_tools,
            parent_worker_id=getattr(self.launcher, "coordinator_instance_id", None),
        )
