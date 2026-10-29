"""RC7.2 context-economy bridge for one canonical leased WorkItem.

This is an additive bridge specialization. It preserves the RC7 one-Task / one-
lease / one-Attempt output semantics while allowing a caller to provide an
execution-only SemanticWorkDescriptor. The descriptor never replaces Task truth.

When no descriptor is supplied, prompt compilation is exactly delegated to the
RC7 DshTaskWorkerBridge. When supplied, the Worker receives:

- canonical Task input refs as lineage only;
- a bounded ContextEnvelope projection;
- effective context refs that may use RetryDelta instead of unchanged upstream
  inputs;
- compact canonical ART-* metadata only for refs that are actually eligible for
  hydration in this semantic decision.

True multi-WorkItem ExecutionBatch execution is intentionally NOT implemented
here because that requires a separate lease/Attempt/Evidence contract.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Sequence

from rc6_runtime.agent_runtime import WorkerAssignment

from .dsh_worker_bridge import (
    DshTaskWorkerBridge,
    DshWorkerBridgeError,
    _COMPACT_OUTPUT_CONTRACT,
    _REQUIREMENT_TRACE_CONTRACT,
    _SEMANTIC_PAYLOAD_HINTS,
    _compact_artifact_input_projection,
)
from .models import ContractError, Task
from .rc72_context_economy import (
    ContextEnvelopeBuilder,
    ExecutionMode,
    SemanticWorkDescriptor,
)
from .rc72_model_usage import TokenUsageAuditService
from .rc72_retry_context import RetryContextAuditService
from .rc72_model_usage_worker_bridge import Rc72TokenUsageLauncherProxy


ContextDescriptorResolver = Callable[[Task], Optional[SemanticWorkDescriptor]]


class Rc72ContextAwareDshTaskWorkerBridge(DshTaskWorkerBridge):
    """Compile bounded-context prompts without changing canonical Task truth."""

    def __init__(
        self,
        control: Any,
        launcher: Any,
        *,
        node_policies: Optional[Dict[str, Any]] = None,
        context_descriptor_resolver: Optional[ContextDescriptorResolver] = None,
        retry_context_audit: Optional[RetryContextAuditService] = None,
        token_usage_audit: Optional[TokenUsageAuditService] = None,
    ) -> None:
        super().__init__(control, launcher, node_policies=node_policies)
        self.context_descriptor_resolver = context_descriptor_resolver
        self.retry_context_audit = retry_context_audit
        self.token_usage_audit = token_usage_audit
        if self.token_usage_audit is None:
            release_id = getattr(control, "release_id", None)
            truth = getattr(control, "truth", None)
            if isinstance(release_id, str) and release_id.strip() and truth is not None:
                self.token_usage_audit = TokenUsageAuditService(truth, release_id=release_id)
        if self.token_usage_audit is not None:
            self.launcher = Rc72TokenUsageLauncherProxy(self.launcher, self.token_usage_audit)

    @staticmethod
    def _validate_descriptor(task: Task, descriptor: SemanticWorkDescriptor) -> None:
        if descriptor.workitem_id != task.task_id:
            raise DshWorkerBridgeError("RC72_CONTEXT_WORKITEM_MISMATCH")
        if descriptor.mission_id != task.mission_id:
            raise DshWorkerBridgeError("RC72_CONTEXT_MISSION_MISMATCH")
        if descriptor.node != task.node:
            raise DshWorkerBridgeError("RC72_CONTEXT_NODE_MISMATCH")
        if tuple(descriptor.input_refs) != tuple(dict.fromkeys(task.input_artifact_refs)):
            raise DshWorkerBridgeError("RC72_CONTEXT_CANONICAL_INPUT_LINEAGE_MISMATCH")
        if tuple(descriptor.gap_refs) != tuple(dict.fromkeys(task.gap_refs)):
            raise DshWorkerBridgeError("RC72_CONTEXT_CANONICAL_GAP_LINEAGE_MISMATCH")

    @staticmethod
    def _effective_context_refs(descriptor: SemanticWorkDescriptor) -> Sequence[str]:
        retry = descriptor.retry_delta
        if retry is not None and not retry.requires_full_context:
            return retry.refs()
        return tuple(dict.fromkeys((*descriptor.input_refs, *descriptor.gap_refs)))

    @staticmethod
    def _first_action_for_refs(
        refs: Sequence[str],
        assignment: WorkerAssignment,
    ) -> str:
        read_tool = next(
            (
                str(tool)
                for tool in assignment.allowed_tools
                if isinstance(tool, str) and tool.endswith("__read_text")
            ),
            None,
        )
        first_file_ref = next(
            (
                str(ref)
                for ref in refs
                if isinstance(ref, str) and ref.startswith("file://")
            ),
            None,
        )
        if not read_tool or not first_file_ref:
            return ""
        path = first_file_ref[len("file://") :]
        if not path:
            return ""
        action = {"tool": read_tool, "arguments": {"path": path}}
        return (
            "MANDATORY_FIRST_ACTION="
            + json.dumps(action, ensure_ascii=False, sort_keys=True)
            + "\nBefore any assistant prose, emit this exact native structured tool call. "
            "Do not explain, plan, restate, or simulate it. Wait for the real tool result, then "
            "continue the leased task and use further allowed tools when evidence requires them."
        )

    def _observe_retry_context(
        self,
        task: Task,
        assignment: WorkerAssignment,
        descriptor: SemanticWorkDescriptor,
    ) -> Optional[Dict[str, Any]]:
        audit = self.retry_context_audit
        if audit is None:
            return None
        try:
            return audit.observe(
                task=task,
                attempt_id=assignment.attempt_id,
                assignment_id=assignment.assignment_id,
                descriptor=descriptor,
            )
        except ContractError as exc:
            raise DshWorkerBridgeError(str(exc)) from exc

    def compile_prompt(self, task: Task, assignment: WorkerAssignment) -> str:
        resolver = self.context_descriptor_resolver
        descriptor = resolver(task) if resolver is not None else None
        if descriptor is None:
            return super().compile_prompt(task, assignment)
        if not isinstance(descriptor, SemanticWorkDescriptor):
            raise DshWorkerBridgeError("RC72_CONTEXT_DESCRIPTOR_INVALID")
        self._validate_descriptor(task, descriptor)
        if descriptor.execution_mode == ExecutionMode.DETERMINISTIC:
            raise DshWorkerBridgeError("RC72_DETERMINISTIC_WORK_MUST_NOT_COMPILE_LLM_PROMPT")

        retry_context = self._observe_retry_context(task, assignment, descriptor)
        envelope = ContextEnvelopeBuilder.build([descriptor])
        envelope_projection = envelope.as_prompt_projection()
        retry = descriptor.retry_delta
        context_mode = "NORMAL"
        if retry is not None:
            context_mode = "FULL_CONTEXT_RETRY" if retry.requires_full_context else "RETRY_DELTA"
            envelope_projection["full_context_reason"] = retry.full_context_reason
        elif retry_context is not None and retry_context.get("observation_status") == "UNKNOWN":
            context_mode = "RETRY_DELTA_UNKNOWN"

        effective_context_refs = tuple(self._effective_context_refs(descriptor))
        artifact_projection = _compact_artifact_input_projection(
            self.control.truth,
            tuple(ref for ref in effective_context_refs if ref.startswith("ART-")),
        )
        expected_id, expected_type = self.expected_output(task)
        retry_context_projection = {
            "observation_status": (
                retry_context.get("observation_status") if retry_context is not None else "NOT_APPLICABLE"
            ),
            "retry_context_id": (
                retry_context.get("retry_context_id") if retry_context is not None else None
            ),
            "parent_attempt_id": (
                retry_context.get("parent_attempt_id") if retry_context is not None else None
            ),
        }
        contract = {
            "mission_id": task.mission_id,
            "task_id": task.task_id,
            "node": task.node,
            "task_type": task.task_type,
            "objective": task.objective,
            "scope": assignment.scope,
            "input_artifact_refs": list(task.input_artifact_refs),
            "lineage_rule": (
                "input_artifact_refs are canonical parent lineage and MUST remain in the returned artifact parent_refs. "
                "Do not hydrate unchanged lineage merely because it is listed here."
            ),
            "effective_context_refs": list(effective_context_refs),
            "context_mode": context_mode,
            "context_envelope": envelope_projection,
            "canonical_input_artifacts": artifact_projection,
            "artifact_input_rule": (
                "Hydrate/use effective_context_refs only for this semantic decision. For ART-* effective refs, use "
                "canonical_input_artifacts; if re-query is necessary, use canonical_truth_query exactly. Never "
                "guess artifact_type or probe unrelated R1 entities."
            ),
            "gap_refs": list(task.gap_refs),
            "acceptance_criteria": list(task.acceptance_criteria),
            "required_capabilities": list(task.required_capabilities),
            "allowed_tools": list(assignment.allowed_tools),
            "model_economy": {
                "execution_mode": descriptor.execution_mode.value,
                "mission_criticality": descriptor.mission_criticality.value,
                "semantic_cost_class": descriptor.semantic_cost_class.value,
                "batch_eligible": bool(descriptor.batch_eligible),
                "context_sha256": envelope.context_sha256,
                "retry_context": retry_context_projection,
            },
            "expected_output": {
                "artifact_id": expected_id,
                "artifact_type": expected_type,
            },
        }
        schema: Dict[str, Any] = {
            "task_id": task.task_id,
            "artifact": {
                "artifact_id": expected_id,
                "artifact_type": expected_type,
                "content_ref": "worker-declared source reference; runtime will persist canonical payload",
                "parent_refs": "list[str] containing every canonical input_artifact_ref",
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
            "output_budget_contract": _COMPACT_OUTPUT_CONTRACT,
        }
        if task.node == "REQUIREMENT_ANALYSIS":
            schema["semantic_payload"]["requirement_trace_contract"] = dict(_REQUIREMENT_TRACE_CONTRACT)

        semantic_instruction = (
            "Hydrate/use only effective_context_refs for the current semantic decision; canonical input_artifact_refs "
            "remain required output lineage. "
        )
        if descriptor.execution_mode == ExecutionMode.HYBRID:
            semantic_instruction += "Run deterministic/tool evidence steps first and use semantic reasoning only for unresolved judgment. "
        prompt = (
            "You are an RC7 professional worker executing one leased task. "
            "Do not evaluate or mark the task PASS. Do not return an Evaluation object. "
            "You MUST call at least one allowed real tool; a text-only answer is invalid. "
            + semantic_instruction
            + "Produce evidence-backed candidate output, put the professional node result in semantic_payload, and return "
            "exactly one JSON object. Keep the final JSON compact and obey RETURN_SCHEMA evidence binding exactly.\n"
            "TASK_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )
        first_action = self._first_action_for_refs(effective_context_refs, assignment)
        if first_action:
            prompt += "\n" + first_action
        return prompt
