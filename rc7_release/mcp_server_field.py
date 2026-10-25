"""Bank-field RC7 MCP wrapper for attempt-scoped CAT and conditional roles.

The base RC7 MCP remains the compatibility surface. New Bank graph-v2 Missions
run this wrapper so failure diagnosis cannot accept Agent-supplied CAT results,
and diagnostic/recovery workers can keep their dedicated authority roles rather
than impersonating the EXECUTION producer lease owner.
"""
from __future__ import annotations

import copy
import json
import sys
from typing import Any, Dict, Mapping, Optional, Tuple

from rc7_release import mcp_server as base
from rc7_runtime.attempt_cat import AttemptCatQueryService, cat_required_for_context
from rc7_runtime.execution_chain_evidence import CHAIN_TOOLS, record_chain_call, validate_chain_context
from rc7_runtime.execution_recovery_conformance import contract_enabled as recovery_contract_enabled
from rc7_runtime.real_executor_provenance import (
    RealExecutorProvenanceGate,
    contract_enabled as real_executor_contract_enabled,
)


PROTOCOL_VERSION = base.PROTOCOL_VERSION
SERVER_NAME = base.SERVER_NAME
SERVER_VERSION = base.SERVER_VERSION + "+bank-field-runtime"


def _schema() -> Dict[str, Any]:
    s = {"type": "string", "minLength": 1}
    correlation = {
        "type": "object",
        "properties": {
            "applications": {"type": "array", "items": s, "minItems": 1},
            "window_start": {"type": "integer"},
            "window_end": {"type": "integer"},
            "request_id": s,
            "trace_id": s,
            "business_id": s,
        },
        "required": ["applications", "window_start", "window_end"],
        "additionalProperties": False,
    }
    return {
        "name": "attempt_cat_query",
        "description": (
            "Runtime-owned CAT correlation for one failed execution Attempt. "
            "The provider is deployment-bound BANK_CAT_QUERY; Agent-supplied CAT results are forbidden. "
            "Use before failure_diagnose when CATPolicy requires CAT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission_context": base._mission_context_schema(),
                "attempt_id": s,
                "target_id": s,
                "correlation": correlation,
            },
            "required": ["mission_context", "attempt_id", "target_id", "correlation"],
            "additionalProperties": False,
        },
    }


def _truth():
    return base.rc6._truth_runtime()


def _cat_service() -> AttemptCatQueryService:
    return AttemptCatQueryService(_truth(), base.rc6._state_root())


def _raw_context(arguments: Mapping[str, Any]) -> Dict[str, str]:
    raw = arguments.get("mission_context")
    if not isinstance(raw, Mapping):
        raise RuntimeError("MISSION_CONTEXT_REQUIRED")
    context = {
        "mission_id": str(raw.get("mission_id") or "").strip(),
        "task_id": str(raw.get("task_id") or "").strip(),
        "worker_id": str(raw.get("worker_id") or "").strip(),
    }
    if not all(context.values()):
        raise RuntimeError("MISSION_CONTEXT_FIELDS_REQUIRED")
    return context


def _chain_context(arguments: Mapping[str, Any], tool_name: str) -> Tuple[Dict[str, str], str]:
    context = _raw_context(arguments)
    worker_arg = str(arguments.get("worker_id") or "").strip()
    if worker_arg and worker_arg != context["worker_id"]:
        raise RuntimeError("MISSION_CONTEXT_WORKER_ARGUMENT_MISMATCH")
    raw_failure = arguments.get("context")
    if not isinstance(raw_failure, Mapping):
        raise RuntimeError("FAILURE_CONTEXT_REQUIRED")
    attempt_id = str(raw_failure.get("attempt_id") or "").strip()
    validate_chain_context(
        _truth(),
        mission_id=context["mission_id"],
        task_id=context["task_id"],
        worker_id=context["worker_id"],
        tool_name=tool_name,
        attempt_id=attempt_id,
    )
    return context, attempt_id


def _current_failed_attempt(attempt_id: str, target_id: str) -> Dict[str, Any]:
    attempt_id = str(attempt_id or "").strip()
    target_id = str(target_id or "").strip()
    if not attempt_id or not target_id:
        raise RuntimeError("ATTEMPT_CAT_FAILURE_CONTEXT_IDENTITY_REQUIRED")
    rows = _truth().query("execution_attempt", attempt_id=attempt_id)
    if len(rows) != 1:
        raise RuntimeError("ATTEMPT_CAT_EXECUTION_ATTEMPT_NOT_UNIQUE")
    attempt = dict(rows[0])
    if str(attempt.get("status") or "").upper() != "FAIL":
        raise RuntimeError("ATTEMPT_CAT_REQUIRES_FAILED_ATTEMPT")
    if str(attempt.get("target_id") or "") != target_id:
        raise RuntimeError("ATTEMPT_CAT_TARGET_MISMATCH")
    if not str(attempt.get("layer") or "").strip():
        raise RuntimeError("ATTEMPT_CAT_FAILURE_CONTEXT_LAYER_REQUIRED")
    return attempt


def _legacy_real_action(attempt: Mapping[str, Any]) -> bool:
    """Compatibility only for Missions created before provenance-contract opt-in.

    The value is derived exclusively from canonical R1 Attempt truth, never MCP
    caller fields. New Bank Missions are fail-closed by RealExecutorProvenanceGate.
    """
    refs = tuple(
        str(ref) for ref in (attempt.get("tool_call_refs") or ())
        if isinstance(ref, str) and ref
    )
    layer = str(attempt.get("layer") or "").upper()
    if layer == "L3":
        # Old RC7 runners used both api-runtime:// receipts and generic governed
        # tool refs. This path exists only when the new provenance contract is
        # absent; it must never override a contracted Mission.
        return any(ref.startswith("api-runtime://APIREC-") or ref.startswith("tool://") for ref in refs)
    non_business = (
        "process://", "runner-process://", "stdout://", "stderr://",
        "validation-manifest://",
    )
    return any(not ref.startswith(non_business) for ref in refs)


def _trusted_failure_context(
    context: Mapping[str, str],
    *,
    attempt_id: str,
    target_id: str,
    correlation: Optional[Mapping[str, Any]],
    caller_failure: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive CAT policy facts from current R1/runtime provenance, not the Agent.

    Caller identity fields are allowed only as equality assertions. Policy facts
    (real action, remote integration and dispatch state) are runtime-owned.
    NOT_DISPATCHED is intentionally never inferred from caller data; without a
    trusted dispatch receipt L4-L7 stay UNKNOWN and therefore CAT-required.
    """
    attempt = _current_failed_attempt(attempt_id, target_id)
    layer = str(attempt.get("layer") or "").upper()
    if isinstance(caller_failure, Mapping):
        caller_attempt = str(caller_failure.get("attempt_id") or "").strip()
        caller_target = str(caller_failure.get("target_id") or "").strip()
        caller_layer = str(caller_failure.get("layer") or "").strip().upper()
        if caller_attempt and caller_attempt != attempt_id:
            raise RuntimeError("ATTEMPT_CAT_FAILURE_CONTEXT_ATTEMPT_MISMATCH")
        if caller_target and caller_target != target_id:
            raise RuntimeError("ATTEMPT_CAT_FAILURE_CONTEXT_TARGET_MISMATCH")
        if caller_layer and caller_layer != layer:
            raise RuntimeError("ATTEMPT_CAT_FAILURE_CONTEXT_LAYER_MISMATCH")

    truth = _truth()
    if real_executor_contract_enabled(truth, context["mission_id"]):
        provenance = RealExecutorProvenanceGate(truth).require_attempt(
            context["mission_id"], context["task_id"], attempt_id, attempt
        )
        real_action_executed = provenance.status == "PASS"
    else:
        # Compatibility for durable pre-contract Missions. No caller-supplied
        # action/dispatch fact is consumed here.
        real_action_executed = _legacy_real_action(attempt)

    # CAT's remote-integration bit only affects L1/L2 policy. L3-L7 are governed
    # by their explicit rules. Until a dedicated trusted L1/L2 remote receipt is
    # available, those layers fail closed to "not proven remote" rather than
    # accepting an Agent assertion.
    remote_integration = False
    return {
        "attempt_id": attempt_id,
        "target_id": target_id,
        "layer": layer,
        "real_action_executed": bool(real_action_executed),
        "remote_integration": remote_integration,
        "business_action_state": "UNKNOWN",
        "correlation": dict(correlation or {}),
    }


def _result_payload(response: Mapping[str, Any]) -> Dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, Mapping) or result.get("isError"):
        raise RuntimeError("MCP_RESULT_NOT_SUCCESS")
    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], Mapping):
        raise RuntimeError("MCP_RESULT_CONTENT_REQUIRED")
    text = content[0].get("text")
    if not isinstance(text, str):
        raise RuntimeError("MCP_RESULT_TEXT_REQUIRED")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("MCP_RESULT_JSON_OBJECT_REQUIRED")
    return payload


def _annotate_diagnosis(
    *,
    response: Mapping[str, Any],
    cat_required: bool,
    cat_result: Optional[Mapping[str, Any]],
) -> None:
    payload = _result_payload(response)
    diagnosis = payload.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        raise RuntimeError("FAILURE_DIAGNOSIS_RESULT_REQUIRED")
    diagnosis_id = str(diagnosis.get("diagnosis_id") or "").strip()
    attempt_id = str(diagnosis.get("attempt_id") or "").strip()
    rows = _truth().query("failure_diagnosis", diagnosis_id=diagnosis_id)
    if len(rows) != 1 or str(rows[0].get("attempt_id") or "") != attempt_id:
        raise RuntimeError("FAILURE_DIAGNOSIS_TRUTH_NOT_UNIQUE")
    row = dict(rows[0])
    row["artifact_version"] = int(row.get("artifact_version", 1)) + 1
    row["cat_required"] = bool(cat_required)
    row["cat_queried"] = bool(cat_result is not None)
    row["cat_query_evidence_id"] = str(cat_result.get("cat_query_evidence_id") or "") if cat_result else None
    _truth().append_atomic("FAILURE_DIAGNOSIS_UPSERTED", row)


def _handle_attempt_cat(message: Mapping[str, Any]) -> Dict[str, Any]:
    msg_id = message.get("id")
    params = message.get("params") or {}
    arguments = params.get("arguments") or {}
    context = _raw_context(arguments)
    if not recovery_contract_enabled(_truth(), context["mission_id"]):
        raise RuntimeError("EXECUTION_RECOVERY_CONTRACT_REQUIRED_FOR_ATTEMPT_CAT")
    attempt_id = str(arguments.get("attempt_id") or "")
    target_id = str(arguments.get("target_id") or "")
    correlation = arguments.get("correlation") or {}
    failure_context = _trusted_failure_context(
        context,
        attempt_id=attempt_id,
        target_id=target_id,
        correlation=correlation,
    )
    result = _cat_service().query(
        mission_id=context["mission_id"],
        task_id=context["task_id"],
        worker_id=context["worker_id"],
        attempt_id=attempt_id,
        target_id=target_id,
        correlation=correlation,
        failure_context=failure_context,
    )
    return {"jsonrpc": "2.0", "id": msg_id, "result": base._text(result)}


def _handle_chain(message: Mapping[str, Any], name: str) -> Dict[str, Any]:
    forwarded = copy.deepcopy(dict(message))
    params = forwarded.setdefault("params", {})
    arguments = dict(params.get("arguments") or {})
    context, attempt_id = _chain_context(arguments, name)
    contracted = recovery_contract_enabled(_truth(), context["mission_id"])
    arguments.pop("mission_context", None)

    cat_result = None
    cat_required = False
    if name == "failure_diagnose" and contracted:
        if "cat_result" in arguments:
            raise RuntimeError("AGENT_SUPPLIED_CAT_RESULT_FORBIDDEN")
        failure_context = arguments.get("context")
        if not isinstance(failure_context, Mapping):
            raise RuntimeError("FAILURE_CONTEXT_REQUIRED")
        target_id = str(failure_context.get("target_id") or "").strip()
        trusted_failure = _trusted_failure_context(
            context,
            attempt_id=attempt_id,
            target_id=target_id,
            correlation=failure_context.get("correlation") if isinstance(failure_context.get("correlation"), Mapping) else None,
            caller_failure=failure_context,
        )
        cat_required = cat_required_for_context(trusted_failure)
        durable = _cat_service().require_for_failure_context(
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            worker_id=context["worker_id"],
            failure_context=trusted_failure,
        )
        if durable is not None:
            cat_result = durable
            arguments["cat_result"] = {
                "tool_call_ref": durable["tool_call_ref"],
                "evidence_ref": durable["evidence_ref"],
                "signals": durable["signals"],
            }
        # Base RC6 only knows FailureContext, not RC7.1 business_action_state.
        # Override the shared policy facts with runtime-owned values so caller
        # self-report cannot weaken downstream diagnosis behavior.
        forwarded_failure = dict(failure_context)
        forwarded_failure["attempt_id"] = trusted_failure["attempt_id"]
        forwarded_failure["target_id"] = trusted_failure["target_id"]
        forwarded_failure["layer"] = trusted_failure["layer"]
        forwarded_failure["real_action_executed"] = trusted_failure["real_action_executed"]
        forwarded_failure["remote_integration"] = trusted_failure["remote_integration"]
        forwarded_failure.pop("business_action_state", None)
        arguments["context"] = forwarded_failure
    params["arguments"] = arguments
    response = base.rc6.handle(forwarded)
    if not base._response_is_error(response):
        record_chain_call(
            _truth(),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            worker_id=context["worker_id"],
            tool_name=name,
            attempt_id=attempt_id,
            result=response,
        )
        if name == "failure_diagnose" and contracted:
            _annotate_diagnosis(
                response=response,
                cat_required=cat_required,
                cat_result=cat_result,
            )
    return response


def handle(message: Dict[str, Any]):
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        response = base.handle(message)
        if isinstance(response, dict) and isinstance(response.get("result"), dict):
            response["result"]["serverInfo"] = {"name": SERVER_NAME, "version": SERVER_VERSION}
            response["result"]["instructions"] = str(response["result"].get("instructions") or "") + (
                " Contracted Bank Missions require runtime attempt_cat_query before CAT-required failure_diagnose; "
                "Agent-supplied cat_result is forbidden. Diagnostic/recovery roles emit EXECUTION_CHAIN_CALL truth."
            )
        return response
    if method == "tools/list":
        response = base.handle(message)
        if isinstance(response, dict):
            result = response.get("result")
            if isinstance(result, dict) and isinstance(result.get("tools"), list):
                if not any(isinstance(tool, dict) and tool.get("name") == "attempt_cat_query" for tool in result["tools"]):
                    result["tools"].append(_schema())
        return response
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        try:
            if name == "attempt_cat_query":
                return _handle_attempt_cat(message)
            if name in CHAIN_TOOLS:
                arguments = params.get("arguments") or {}
                context = arguments.get("mission_context") if isinstance(arguments, Mapping) else None
                mission_id = str(context.get("mission_id") or "") if isinstance(context, Mapping) else ""
                if mission_id and recovery_contract_enabled(_truth(), mission_id):
                    return _handle_chain(message, name)
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
    return base.handle(message)


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            response = handle(json.loads(raw))
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())