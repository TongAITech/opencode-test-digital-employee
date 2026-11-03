"""RC7.2 C10 production Mission economy composition, without Mission Factory edits.

The configured/custom host path already returns native launchers.  The command
line calls this composer before the Factory receives them, so the existing
factory's concrete type, lease and native N1 gates remain intact.

The R1 lookup resolves the exact task, including independently created
reviewer assignments.  No inferred task identity from a prompt is allowed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .rc72_model_economy import (
    BankCostWindowConfig, TokenEconomyError, TokenEconomyService,
    ModelCallClass, MissionCriticality, SemanticCostClass,
)
from .rc72_model_usage import TokenUsageAuditService
from .rc72_schedule_semantics import WorkScheduleSemanticsService
from .rc72_production_economy_wiring import (
    ProductionEconomyBindingError, bind_production_model_economy,
)


_ROLE_NODE = {
    "reality": "N1_REALITY",
    "requirement": "N2_REQUIREMENT",
    "requirement_review": "N2_REQUIREMENT",
    "source": "N3_CODE_ANALYSIS",
    "source_review": "N3_CODE_ANALYSIS",
    "code": "N3_CODE_ANALYSIS",
    "code_review": "N3_CODE_ANALYSIS",
    "design": "N4_TEST_DESIGN",
    "design_review": "N4_TEST_DESIGN",
    "data": "N5_TEST_DATA",
    "data_verify": "N5_TEST_DATA",
}
_REVIEW_ROLES = frozenset(
    ("requirement_review", "source_review", "code_review", "design_review", "data_verify")
)
_DEFAULT_TARGETS = {
    "max_total_tokens": 40_000_000,
    "max_model_calls": 100_000,
    "max_single_call_tokens": 128_000,
    "max_retry_tokens": 40_000_000,
    "max_retry_calls": 100_000,
    "max_same_context_calls": 2,
    "require_measured_usage": True,
    "require_complete_lineage": True,
}
_TASK_SCOPE = re.compile(r"^task:([^/]+)(?:/attempt:([^/]+))?$")


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionEconomyBindingError("RC72_ECONOMY_%s_REQUIRED" % name.upper())
    return value.strip()


def _one(truth: TruthRuntime, kind: str, **fields: str) -> Dict[str, Any]:
    rows = truth.query(kind, **fields)
    if len(rows) != 1:
        raise ProductionEconomyBindingError("RC72_ECONOMY_%s_NOT_UNIQUE" % kind.upper())
    return rows[0]


def _workitem_for_assignment(
    truth: TruthRuntime, assignment: Any, role: str, mission_id: str,
) -> Dict[str, Any]:
    if _required(getattr(assignment, "mission_id", None), "mission_id") != mission_id:
        raise ProductionEconomyBindingError("RC72_ECONOMY_MISSION_LINEAGE_MISMATCH")
    scope = _required(getattr(assignment, "scope", None), "scope")
    matched = _TASK_SCOPE.fullmatch(scope)
    if role == "reality":
        if not scope.startswith("mission-node://"):
            raise ProductionEconomyBindingError("RC72_ECONOMY_N1_NATIVE_SCOPE_REQUIRED")
        receipt = _one(
            truth, "rc72_mission_node_worker_assignment",
            mission_id=mission_id,
            worker_instance_id=_required(
                getattr(assignment, "worker_instance_id", None), "worker_instance_id"
            ),
        )
        if scope != "mission-node://%s" % receipt.get("mission_node_id"):
            raise ProductionEconomyBindingError("RC72_ECONOMY_N1_SCOPE_MISMATCH")
        workitem_id = _required(receipt.get("workitem_id"), "workitem_id")
    elif role in _REVIEW_ROLES:
        if matched:
            raise ProductionEconomyBindingError("RC72_ECONOMY_REVIEWER_MUST_USE_ARTIFACT_SCOPE")
        artifact_id = scope[len("artifact:"):] if scope.startswith("artifact:") else scope
        artifact = _one(truth, "rc7_artifact", artifact_id=artifact_id)
        if artifact.get("mission_id") != mission_id:
            raise ProductionEconomyBindingError("RC72_ECONOMY_REVIEW_ARTIFACT_MISSION_MISMATCH")
        workitem_id = _required(artifact.get("producer_task_id"), "producer_task_id")
    else:
        if matched is None:
            raise ProductionEconomyBindingError("RC72_ECONOMY_NATIVE_TASK_SCOPE_REQUIRED")
        workitem_id = matched.group(1)
        if matched.group(2) and matched.group(2) != getattr(assignment, "attempt_id", None):
            raise ProductionEconomyBindingError("RC72_ECONOMY_ATTEMPT_SCOPE_MISMATCH")

    task = _one(truth, "rc7_task", task_id=workitem_id)
    if task.get("mission_id") != mission_id:
        raise ProductionEconomyBindingError("RC72_ECONOMY_TASK_MISSION_MISMATCH")
    if role not in _REVIEW_ROLES and task.get("lease_owner") != getattr(assignment, "worker_instance_id", None):
        raise ProductionEconomyBindingError("RC72_ECONOMY_PRODUCER_LEASE_MISMATCH")
    return task


def canonical_role_metadata_resolver(
    truth: TruthRuntime, *, role: str, mission_id: str,
):
    """Authoritative R1 resolver for native producer and reviewer model calls."""
    if role not in _ROLE_NODE:
        raise ProductionEconomyBindingError("RC72_ECONOMY_ROLE_INVALID")

    def resolve(assignment: Any) -> Dict[str, Any]:
        task = _workitem_for_assignment(truth, assignment, role, mission_id)
        workitem_id = str(task["task_id"])
        schedule = truth.query(
            "rc72_work_schedule_semantics", mission_id=mission_id, workitem_id=workitem_id
        )
        if len(schedule) > 1:
            raise ProductionEconomyBindingError("RC72_ECONOMY_SCHEDULE_SEMANTICS_AMBIGUOUS")
        schedule = schedule[0] if schedule else {}
        execution_mode = schedule.get("execution_mode", "SEMANTIC")
        if execution_mode not in {"DETERMINISTIC", "SEMANTIC", "HYBRID"}:
            raise ProductionEconomyBindingError("RC72_ECONOMY_EXECUTION_MODE_INVALID")
        call_class = (
            ModelCallClass.DETERMINISTIC_NO_LLM
            if execution_mode == "DETERMINISTIC" else ModelCallClass.LLM_REQUIRED
        )
        criticality = schedule.get("mission_criticality", MissionCriticality.UNKNOWN.value)
        cost = schedule.get("semantic_cost_class", SemanticCostClass.UNKNOWN.value)
        if criticality not in {v.value for v in MissionCriticality}:
            raise ProductionEconomyBindingError("RC72_ECONOMY_CRITICALITY_INVALID")
        if cost not in {v.value for v in SemanticCostClass}:
            raise ProductionEconomyBindingError("RC72_ECONOMY_SEMANTIC_COST_INVALID")
        attempt_id = _required(getattr(assignment, "attempt_id", None), "attempt_id")
        bindings = truth.query(
            "rc72_workitem_attempt_binding", mission_id=mission_id,
            workitem_id=workitem_id, attempt_id=attempt_id,
        )
        if len(bindings) > 1:
            raise ProductionEconomyBindingError("RC72_ECONOMY_ATTEMPT_LINEAGE_AMBIGUOUS")
        retry = bool(bindings and bindings[0].get("parent_attempt_id"))
        return {
            "mission_id": mission_id,
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "agent_id": _required(getattr(assignment, "agent_id", None), "agent_id"),
            "node": _ROLE_NODE[role],
            "stage": _required(task.get("node"), "stage"),
            "call_class": call_class.value,
            "mission_criticality": criticality,
            "semantic_cost_class": cost,
            "retry": retry,
        }

    return resolve


def read_mission_economy_config(path: Optional[str]) -> Dict[str, Any]:
    """Read optional trusted, operator-owned policy; no model-controlled knobs."""
    if path is None:
        return {}
    source = Path(_required(path, "config_path")).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError):
        raise ProductionEconomyBindingError("RC72_ECONOMY_CONFIG_READ_FAILED") from None
    if not isinstance(raw, dict) or set(raw) - {"bank_cost_window", "soft_targets"}:
        raise ProductionEconomyBindingError("RC72_ECONOMY_CONFIG_KEYS_INVALID")
    if "bank_cost_window" in raw:
        BankCostWindowConfig.from_mapping(raw["bank_cost_window"])
    if "soft_targets" in raw:
        targets = raw["soft_targets"]
        if not isinstance(targets, dict) or set(targets) != set(_DEFAULT_TARGETS):
            raise ProductionEconomyBindingError("RC72_ECONOMY_TARGET_KEYS_INVALID")
        for name, value in targets.items():
            if name.startswith("require_"):
                if not isinstance(value, bool):
                    raise ProductionEconomyBindingError("RC72_ECONOMY_TARGET_BOOLEAN_INVALID")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ProductionEconomyBindingError("RC72_ECONOMY_TARGET_INTEGER_INVALID")
    return raw


def bind_release_batch_model_economy(
    truth: TruthRuntime, *,
    workers: Mapping[str, Any],
    release_id: str,
    mission_id: str,
    policy: Optional[Mapping[str, Any]] = None,
) -> TokenEconomyService:
    """Bind all 11 native role launchers before the real Factory can dispatch.

    Budget is soft and persistent. An existing R1 budget is retained across cold
    restarts. Validate ALL launchers and authoritative mission identity before
    instrumenting any launcher (no half-bound role fleet).
    """
    release_id = _required(release_id, "release_id")
    mission_id = _required(mission_id, "mission_id")
    mission = _one(truth, "rc7_mission", mission_id=mission_id)
    if mission.get("release_id") != release_id:
        raise ProductionEconomyBindingError("RC72_ECONOMY_RELEASE_MISSION_MISMATCH")
    if not isinstance(workers, Mapping) or set(workers) != set(_ROLE_NODE):
        raise ProductionEconomyBindingError("RC72_ECONOMY_ALL_NATIVE_ROLES_REQUIRED")
    launchers = []
    for role in _ROLE_NODE:
        launcher = getattr(workers[role], "launcher", None)
        if (
            not isinstance(launcher, DshHeadlessWorkerLauncher)
            or launcher.truth is not truth
            or launcher.release_id != release_id
            or getattr(launcher, "_rc72_production_economy_bound", False)
        ):
            raise ProductionEconomyBindingError("RC72_ECONOMY_NATIVE_ROLE_SCOPE_MISMATCH:%s" % role)
        launchers.append(launcher)
    if len({id(item) for item in launchers}) != len(launchers):
        raise ProductionEconomyBindingError("RC72_ECONOMY_ROLE_LAUNCHERS_NOT_DISTINCT")
    if not isinstance(policy, (Mapping, type(None))):
        raise ProductionEconomyBindingError("RC72_ECONOMY_POLICY_INVALID")
    policy = dict(policy or {})
    if set(policy) - {"bank_cost_window", "soft_targets"}:
        raise ProductionEconomyBindingError("RC72_ECONOMY_POLICY_KEYS_INVALID")
    window = BankCostWindowConfig.from_mapping(policy["bank_cost_window"]) if "bank_cost_window" in policy else BankCostWindowConfig()
    economy = TokenEconomyService(truth, release_id=release_id, cost_window_config=window)
    budget_rows = truth.query("rc72_token_budget", budget_id=mission_id)
    if len(budget_rows) > 1:
        raise ProductionEconomyBindingError("RC72_ECONOMY_BUDGET_NOT_UNIQUE")
    if not budget_rows:
        targets = dict(_DEFAULT_TARGETS)
        targets.update(policy.get("soft_targets") or {})
        economy.configure_budget(mission_id=mission_id, **targets)
    elif budget_rows[0].get("state") != "ACTIVE":
        raise ProductionEconomyBindingError("RC72_ECONOMY_BUDGET_RETIRED")
    # Install the R1 semantic projection even when the first production run
    # has not constructed an in-memory scheduling control plane.
    WorkScheduleSemanticsService(truth, release_id=release_id)
    audit = TokenUsageAuditService(truth, release_id=release_id)
    for role in _ROLE_NODE:
        bind_production_model_economy(
            workers[role].launcher, economy=economy, usage_audit=audit,
            metadata_resolver=canonical_role_metadata_resolver(
                truth, role=role, mission_id=mission_id,
            ),
        )
    return economy
