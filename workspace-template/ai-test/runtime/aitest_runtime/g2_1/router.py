from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from aitest_runtime.durable_core import canonical_sha256
from .contracts import SessionControlState, TaskRouteRequirement

OPENCODE_AGENT_SESSION = "OPENCODE_AGENT_SESSION"
TASK_OUTCOME_REPORT = "TASK_OUTCOME_REPORT"
G5_DEFECT_HUNTER_CAPABILITIES = frozenset({
    OPENCODE_AGENT_SESSION,
    TASK_OUTCOME_REPORT,
    "DEFECT_ANOMALY_INTAKE",
    "DEFECT_CANDIDATE_FORMATION",
    "EVIDENCE_GAP_ANALYSIS",
    "CROSS_SOURCE_CORRELATION",
    "REPRODUCIBILITY_REASONING",
    "FALSE_POSITIVE_EXCLUSION",
    "DEFECT_TRUTH_ASSESSMENT",
    "RCA_ANALYSIS",
    "DUPLICATE_CORRELATION",
})

@dataclass(frozen=True)
class AgentRole:
    role: str
    agent_name: str
    capabilities: frozenset[str]

class AgentRoleRegistry:
    def __init__(self, roles: list[AgentRole]): self._roles={r.role:r for r in roles}
    @classmethod
    def default(cls):
        session=frozenset({OPENCODE_AGENT_SESSION})
        worker=frozenset({OPENCODE_AGENT_SESSION, TASK_OUTCOME_REPORT})
        return cls([
            AgentRole("PLANNER","aitest-planner",session),
            AgentRole("EXECUTOR","aitest-executor",worker),
            AgentRole("EVALUATOR","aitest-evaluator",worker),
            AgentRole("DIAGNOSIS","aitest-diagnosis",worker),
            AgentRole("DEFECT_HUNTER","aitest-diagnosis",G5_DEFECT_HUNTER_CAPABILITIES),
            AgentRole("KNOWLEDGE","aitest-knowledge",worker),
            # G3 specialists are additive role/capability registrations only.
            # Session lifecycle remains exclusively owned by this Router/R2.5/Supervisor.
            AgentRole("REQUIREMENT_ANALYST","aitest-requirement-analyst",worker | frozenset({"G3_REQUIREMENT_INTELLIGENCE"})),
            AgentRole("CODE_ANALYST","aitest-code-analyst",worker | frozenset({"G3_CODE_INTELLIGENCE", "G3_BANK_COVERAGE_READ"})),
            AgentRole("TEST_STRATEGIST","aitest-test-strategist",worker | frozenset({"G3_TEST_STRATEGY"})),
            AgentRole("CASE_DESIGNER","aitest-case-designer",worker | frozenset({"G3_CASE_DESIGN"})),
        ])
    def resolve(self, role: str) -> AgentRole:
        key=str(role).upper()
        if key not in self._roles: raise RuntimeError(f"SESSION_ROUTER_ROLE_UNAVAILABLE: {key}")
        return self._roles[key]

@dataclass(frozen=True)
class RouteDecision:
    decision: str
    task_id: str
    role: str
    agent_name: str
    logical_agent_id: str
    required_capabilities: tuple[str,...]
    isolation_policy: str
    parallelism_policy: str
    reason: str
    def to_dict(self): return self.__dict__.copy()

class SessionRouter:
    def __init__(self, registry: AgentRoleRegistry): self.registry=registry
    @staticmethod
    def logical_agent_id(agent_name: str, task_id: str) -> str:
        return f"{agent_name}:{canonical_sha256({'task_id':task_id})[:20]}"
    def route_requirement(self, state: SessionControlState, task_id: str) -> TaskRouteRequirement:
        req=state.route(task_id)
        if req is None: raise RuntimeError(f"SESSION_ROUTER_ROUTE_NOT_REGISTERED: {task_id}")
        role=self.registry.resolve(req.role)
        if role.agent_name != req.agent_name: raise RuntimeError("SESSION_ROUTER_ROLE_AGENT_CONFLICT")
        missing=set(req.required_capabilities)-set(role.capabilities)
        if missing: raise RuntimeError(f"SESSION_ROUTER_CAPABILITY_UNAVAILABLE: {sorted(missing)}")
        return req
    def route_task(self, state: SessionControlState, *, task_id: str, latest_attempt: Any=None, session: Any=None) -> RouteDecision:
        req=state.route(task_id)
        if req is None:
            raise RuntimeError(f"SESSION_ROUTER_ROUTE_NOT_REGISTERED: {task_id}")
        logical=self.logical_agent_id(req.agent_name, task_id)
        try:
            role=self.registry.resolve(req.role)
        except RuntimeError:
            return RouteDecision("BLOCK", task_id, req.role, req.agent_name, logical, req.required_capabilities, req.isolation_policy, req.parallelism_policy, "ROLE_UNAVAILABLE")
        if role.agent_name != req.agent_name:
            return RouteDecision("BLOCK", task_id, req.role, req.agent_name, logical, req.required_capabilities, req.isolation_policy, req.parallelism_policy, "ROLE_AGENT_CONFLICT")
        missing=set(req.required_capabilities)-set(role.capabilities)
        if missing:
            return RouteDecision("BLOCK", task_id, req.role, req.agent_name, logical, req.required_capabilities, req.isolation_policy, req.parallelism_policy, "CAPABILITY_UNAVAILABLE:" + ",".join(sorted(missing)))
        if latest_attempt is None:
            decision,reason="CREATE","NO_ATTEMPT"
        elif session is not None and getattr(getattr(session,"status",None),"value",None)=="OPEN":
            attrs=dict(getattr(session,"attributes",{}) or {})
            if attrs.get("opencode_agent") != req.agent_name: decision,reason="ROTATE","ROUTE_CHANGED"
            else: decision,reason="REUSE","ACTIVE_SESSION_MATCHES_ROUTE"
        else: decision,reason="ROTATE","LATEST_SESSION_NOT_OPEN"
        return RouteDecision(decision, task_id, req.role, req.agent_name, logical, req.required_capabilities, req.isolation_policy, req.parallelism_policy, reason)
