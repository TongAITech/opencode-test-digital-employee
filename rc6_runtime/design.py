"""RC6 Wave 6 professional L1-L7 design routing and task isolation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .authority import AuthorityRuntime
from .contracts import DomainValidationError, validate_test_case


class DesignRuntimeError(RuntimeError):
    pass


LAYERS = tuple(f"L{i}" for i in range(1, 8))
SIGNAL_BY_LAYER = {
    "L1": "code_change",
    "L2": "db_or_component_impact",
    "L3": "api_impact",
    "L4": "ui_impact",
    "L5": "cross_system_impact",
    "L6": "performance_risk",
    "L7": "security_risk",
}
TOOLS_BY_LAYER = {
    "L1": ("git", "codegraph", "maven", "junit", "jacoco"),
    "L2": ("git", "codegraph", "db"),
    "L3": ("git", "codegraph", "api"),
    "L4": ("browser-skill", "playwright"),
    "L5": ("browser-skill", "api", "db", "cat"),
    "L6": ("k6",),
    "L7": ("zap", "api", "browser-skill"),
}


@dataclass(frozen=True)
class LayerDecision:
    layer: str
    applicable: bool
    reason: str
    evidence_refs: tuple


@dataclass(frozen=True)
class DesignTask:
    condition_id: str
    layer: str
    worker_id: str
    role: str
    lease_id: str
    scope_ref: str
    artifact_type: str
    allowed_tools: tuple
    generation: int


class LayerApplicabilityRouter:
    """Always returns seven explicit decisions; never a combined layer."""

    def route(self, condition: Dict) -> List[LayerDecision]:
        condition_id = condition.get("id")
        signals = condition.get("signals")
        evidence = condition.get("signal_evidence", {})
        if not isinstance(condition_id, str) or not condition_id.strip():
            raise DesignRuntimeError("CONDITION_ID_REQUIRED")
        if not isinstance(signals, dict):
            raise DesignRuntimeError("CONDITION_SIGNALS_REQUIRED")
        if not isinstance(evidence, dict):
            raise DesignRuntimeError("SIGNAL_EVIDENCE_REQUIRED")
        decisions: List[LayerDecision] = []
        for layer in LAYERS:
            signal = SIGNAL_BY_LAYER[layer]
            if signal not in signals or not isinstance(signals[signal], bool):
                raise DesignRuntimeError(f"LAYER_SIGNAL_MISSING:{layer}:{signal}")
            refs = evidence.get(signal, [])
            if not isinstance(refs, list):
                raise DesignRuntimeError(f"LAYER_SIGNAL_EVIDENCE_INVALID:{layer}")
            applicable = signals[signal]
            if applicable and not refs:
                raise DesignRuntimeError(f"APPLICABLE_LAYER_EVIDENCE_MISSING:{layer}")
            reason = f"{signal}=true" if applicable else f"{signal}=false"
            decisions.append(LayerDecision(layer, applicable, reason, tuple(refs)))
        return decisions


class DesignContextBuilder:
    """Builds bounded reference-only context; raw diff/chat/source blobs are forbidden."""

    FORBIDDEN_KEYS = {"raw_diff", "diff_text", "source_blob", "chat_history", "conversation", "full_source"}

    def build(
        self,
        *,
        condition_ref: str,
        requirement_analysis_ref: str,
        code_analysis_ref: str,
        code_impact_refs: List[str],
        risk_refs: List[str],
        max_refs: int = 32,
    ) -> Dict:
        refs = [condition_ref, requirement_analysis_ref, code_analysis_ref] + list(code_impact_refs) + list(risk_refs)
        if len(refs) > max_refs:
            raise DesignRuntimeError("DESIGN_CONTEXT_REF_BUDGET_EXCEEDED")
        if not all(isinstance(x, str) and x.strip() and "://" in x for x in refs):
            raise DesignRuntimeError("DESIGN_CONTEXT_REQUIRES_ARTIFACT_REFS")
        return {
            "condition_ref": condition_ref,
            "requirement_analysis_ref": requirement_analysis_ref,
            "code_analysis_ref": code_analysis_ref,
            "code_impact_refs": list(code_impact_refs),
            "risk_refs": list(risk_refs),
        }

    def validate_external_payload(self, payload: Dict) -> None:
        if any(k in payload for k in self.FORBIDDEN_KEYS):
            raise DesignRuntimeError("RAW_CONTEXT_FORBIDDEN")


class DesignTaskPlanner:
    def __init__(self, authority: AuthorityRuntime):
        self.authority = authority

    def plan(self, condition_id: str, decisions: List[LayerDecision], *, session_prefix: str = "design") -> List[DesignTask]:
        if {d.layer for d in decisions} != set(LAYERS) or len(decisions) != 7:
            raise DesignRuntimeError("SEVEN_LAYER_DECISIONS_REQUIRED")
        tasks: List[DesignTask] = []
        for decision in sorted(decisions, key=lambda d: d.layer):
            if not decision.applicable:
                continue
            layer = decision.layer
            role = f"{layer}_DESIGN"
            artifact_type = f"case_candidate_{layer.lower()}"
            identity = self.authority.issue_identity(role, "TEST_DESIGN", layer, 0, f"{session_prefix}-{condition_id}-{layer}")
            lease = self.authority.issue_lease(
                identity.worker_id,
                f"condition://{condition_id}",
                [artifact_type],
                TOOLS_BY_LAYER[layer],
            )
            tasks.append(
                DesignTask(
                    condition_id=condition_id,
                    layer=layer,
                    worker_id=identity.worker_id,
                    role=role,
                    lease_id=lease.lease_id,
                    scope_ref=lease.scope_ref,
                    artifact_type=artifact_type,
                    allowed_tools=lease.allowed_tools,
                    generation=identity.generation,
                )
            )
        return tasks

    def rotate_after_context_overflow(self, task: DesignTask, successor_session_id: str) -> DesignTask:
        identity = self.authority.rotate_same_role(task.worker_id, successor_session_id)
        lease = self.authority.issue_lease(
            identity.worker_id,
            task.scope_ref,
            [task.artifact_type],
            task.allowed_tools,
        )
        return DesignTask(
            condition_id=task.condition_id,
            layer=task.layer,
            worker_id=identity.worker_id,
            role=identity.role,
            lease_id=lease.lease_id,
            scope_ref=task.scope_ref,
            artifact_type=task.artifact_type,
            allowed_tools=task.allowed_tools,
            generation=identity.generation,
        )

    def validate_candidate(self, candidate: Dict, task: DesignTask) -> Dict:
        try:
            canonical = validate_test_case(candidate)
        except DomainValidationError as exc:
            raise DesignRuntimeError(str(exc)) from exc
        if canonical["layer"] != task.layer:
            raise DesignRuntimeError("CASE_LAYER_TASK_MISMATCH")
        if canonical["condition_id"] != task.condition_id:
            raise DesignRuntimeError("CASE_CONDITION_TASK_MISMATCH")
        if canonical["status"] != "CANDIDATE":
            raise DesignRuntimeError("DESIGN_WORKER_MAY_ONLY_EMIT_CANDIDATE")
        if candidate.get("worker_id") != task.worker_id or candidate.get("lease_id") != task.lease_id:
            raise DesignRuntimeError("CASE_PROVENANCE_MISMATCH")
        self.authority.authorize_artifact(task.worker_id, task.lease_id, task.artifact_type)
        return canonical
