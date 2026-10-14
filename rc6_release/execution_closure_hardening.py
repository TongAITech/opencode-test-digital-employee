"""Fail-closed hardening for RC6 Execution Closure MCP surfaces.

The frozen/base MCP implementation remains intact. This overlay removes the
ability for a DSH Worker to self-report a successful recovery action. Non-
terminal recovery must execute a trusted, runtime-scoped VerifiedRecoveryAdapter.
It also makes execution-convergence an authorized professional artifact and
turns terminal PRODUCT recovery into a canonical R1 defect candidate.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from rc6_runtime import ExecutionBudgets, ExecutionConvergenceController, RecoveryActionExecutor

from . import execution_closure_mcp as _base
from .recovery_adapter_registry import require_recovery_adapter


_BASE_SCHEMAS = _base.execution_closure_tool_schemas
_BASE_CALL = _base.call_execution_closure_tool
_INSTALLED = False


def execution_closure_tool_schemas() -> List[Dict[str, Any]]:
    tools = deepcopy(_BASE_SCHEMAS())
    for tool in tools:
        name = tool.get("name")
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        required = list(schema.get("required") or [])
        if name == "recovery_execute":
            # Recovery outcome is runtime-owned. A Worker may request an action,
            # but cannot submit {verified:true} as proof of execution.
            properties.pop("action_result", None)
            required = [item for item in required if item != "action_result"]
            tool["description"] = (
                "Execute a runtime-bound VerifiedRecoveryAdapter, enforce budgets/signature loop breaker, "
                "create a fresh Attempt when rerunnable, and record recovery truth in R1."
            )
        elif name == "execution_convergence":
            properties["worker_id"] = {"type": "string"}
            properties["lease_id"] = {"type": "string"}
            for item in ("worker_id", "lease_id"):
                if item not in required:
                    required.insert(0 if item == "worker_id" else 1, item)
        schema["properties"] = properties
        schema["required"] = required
    return tools


def _append_product_defect(*, authority, truth, arguments, diagnosis, recovery_result) -> Optional[Dict[str, Any]]:
    if recovery_result.terminal_status != "PRODUCT_DEFECT_CONFIRMED" or recovery_result.action != "PRODUCT_DEFECT":
        return None
    authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "defect")
    attempts = truth.query(
        "execution_attempt",
        release_id=arguments["release_id"],
        attempt_id=recovery_result.prior_attempt_id,
    )
    if len(attempts) != 1:
        raise RuntimeError("PRODUCT_DEFECT_ATTEMPT_TRUTH_REQUIRED")
    attempt = attempts[0]
    candidate_refs = [ref for ref in recovery_result.output_refs if ref.startswith("defect-candidate://")]
    if len(candidate_refs) != 1:
        raise RuntimeError("PRODUCT_DEFECT_CANDIDATE_REF_REQUIRED")
    candidate_ref = candidate_refs[0]
    defect_id = "DEFECT-" + sha256(
        (recovery_result.prior_attempt_id + "|" + candidate_ref).encode("utf-8")
    ).hexdigest()[:24]
    evidence_refs = list(dict.fromkeys(recovery_result.evidence_refs))
    if not evidence_refs:
        raise RuntimeError("PRODUCT_DEFECT_EVIDENCE_REQUIRED")
    payload = {
        "id": defect_id,
        "release_id": arguments["release_id"],
        "requirement_id": attempt["requirement_id"],
        "tc_id": attempt["tc_id"],
        "attempt_id": recovery_result.prior_attempt_id,
        "title": "SUT violates frozen test oracle after test-side ownership verification",
        "severity": "MEDIUM",
        "status": "CANDIDATE",
        "evidence_refs": evidence_refs,
        "failure_diagnosis_ref": "diagnosis://%s" % diagnosis.diagnosis_id,
        "recovery_action_ref": "recovery://%s" % recovery_result.recovery_action_id,
        "defect_candidate_ref": candidate_ref,
    }
    if diagnosis.root_cause_candidate is not None:
        payload["root_cause_candidate_ref"] = "root-cause://%s" % diagnosis.root_cause_candidate.candidate_id
    receipt = truth.append_atomic("DEFECT_UPSERTED", payload)
    return {"defect": payload, "r1_receipt": asdict(receipt)}


def call_execution_closure_tool(
    name: str,
    arguments: Dict[str, Any],
    *,
    authority,
    truth,
    broker,
    state_root: Path,
) -> Optional[Dict[str, Any]]:
    if name == "failure_diagnose" and arguments.get("rca_candidate"):
        # DiagnosisRuntime authorizes failure_diagnosis/recovery/evidence; RCA is
        # a separate canonical professional artifact and must be authorized too.
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "root_cause_candidate")

    if name == "recovery_execute":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "recovery_action")
        context = _base._failure_context(arguments["context"])
        diagnosis = _base._diagnosis(arguments["diagnosis"])
        decision = _base._decision(arguments["decision"])
        history = _base._history(arguments["history"])
        budgets = ExecutionBudgets(**(arguments.get("budgets") or {}))
        controller = ExecutionConvergenceController(history, budgets)

        adapters = {}
        if decision.action not in RecoveryActionExecutor.TERMINAL_ACTIONS:
            adapters[decision.action] = require_recovery_adapter(state_root, decision.action)
        executor = RecoveryActionExecutor(history=history, convergence=controller, adapters=adapters)
        result = executor.execute(context=context, diagnosis=diagnosis, decision=decision)
        payload = asdict(result)
        payload["release_id"] = arguments["release_id"]
        receipt = truth.append_atomic("RECOVERY_ACTION_UPSERTED", payload)
        defect = _append_product_defect(
            authority=authority,
            truth=truth,
            arguments=arguments,
            diagnosis=diagnosis,
            recovery_result=result,
        )
        return {
            "recovery_action": payload,
            "attempt_history": [asdict(item) for item in history.entries()],
            "r1_receipt": asdict(receipt),
            "defect_candidate": defect,
        }

    if name == "execution_convergence":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "execution_convergence")

    return _BASE_CALL(
        name,
        arguments,
        authority=authority,
        truth=truth,
        broker=broker,
        state_root=state_root,
    )


def install_execution_closure_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _base.execution_closure_tool_schemas = execution_closure_tool_schemas
    _base.call_execution_closure_tool = call_execution_closure_tool
    _INSTALLED = True
