from __future__ import annotations

import copy
import json
import sys
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_release import mcp_server as rc6
from rc7_runtime.case_runtime import CasePreparationService
from rc7_runtime.node_tool_conformance import (
    NODE_TOOL_REQUIREMENTS,
    contract_enabled,
    record_successful_call,
    validate_call_context,
)
from rc7_runtime.truth_overlay import install_rc7_truth_overlay
from .codegraph_mcp import call_codegraph_tool, list_codegraph_tools
from .professional_tools import codegraph_probe, codegraph_query, git_diff, git_show_revision
from .source_tools import read_text


PROTOCOL_VERSION = rc6.PROTOCOL_VERSION
SERVER_NAME = "pfc-aitest-rc7"
SERVER_VERSION = "7.0-field-hardened-runtime-candidate"

install_rc7_truth_overlay()

_TRACKED_BASE_TOOLS = {
    "truth_query",
    "artifact_record",
    "executable_spec_build",
    "automation_reuse_resolve",
    "script_build",
    "script_validate",
    "runner_execute",
    "failure_diagnose",
    "recovery_decide",
    "recovery_execute",
    "execution_convergence",
}
_TRACKED_EXTRA_TOOLS = {
    tool
    for requirements in NODE_TOOL_REQUIREMENTS.values()
    for requirement in requirements
    for tool in requirement.any_of_tools
    if tool not in _TRACKED_BASE_TOOLS
}


def _object(properties: Dict[str, Any], required=None, *, additional: bool = False) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or []),
        "additionalProperties": additional,
    }


def _mission_context_schema() -> Dict[str, Any]:
    s = {"type": "string", "minLength": 1}
    return _object(
        {
            "mission_id": s,
            "task_id": s,
            "worker_id": s,
        },
        ["mission_id", "task_id", "worker_id"],
    )


def _with_context(properties: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(properties)
    out["mission_context"] = _mission_context_schema()
    return out


def _extra_tools():
    s = {"type": "string"}
    a = {"type": "array", "items": s}
    obj = {"type": "object", "additionalProperties": True}
    return [
        {
            "name": "read_text",
            "description": "Read one UTF-8 source file contained by PFC_WORKSPACE or PFC_AITEST_STATE_DIR. Read-only and path-escape protected. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"path": s, "scope": {"type": "string", "enum": ["workspace", "state"]}, "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000}}), ["path"]),
        },
        {
            "name": "git_show_revision",
            "description": "Read one Git commit identity from a workspace-contained repository. Read-only; shell is never used. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s, "ref": s})),
        },
        {
            "name": "git_diff",
            "description": "Read resolved Git revisions, changed files and diff between two refs. Read-only; paths are workspace-contained. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s, "base_ref": s, "head_ref": s, "paths": a, "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000}}), ["base_ref", "head_ref"]),
        },
        {
            "name": "codegraph_probe",
            "description": "Probe the configured CodeGraph executable with --help only. This is discovery evidence, not query readiness. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s})),
        },
        {
            "name": "codegraph_query",
            "description": "Legacy allowlisted CodeGraph CLI query adapter retained for CLI-capable binaries. Prefer codegraph_mcp_tools/codegraph_mcp_call when the configured binary exposes MCP stdio. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s, "args": a, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300}, "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000}}), ["args"]),
        },
        {
            "name": "codegraph_mcp_tools",
            "description": "Start the configured CodeGraph MCP server, dynamically list its real tool names/schemas and label which tools are admitted as read-only. Uses Windows-safe reader threads rather than select(). Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300}})),
        },
        {
            "name": "codegraph_mcp_call",
            "description": "Call one tool only after it was dynamically discovered from CodeGraph tools/list and admitted by the read-only policy. Mutating/index/build tools are rejected. Supply mission_context for durable graph-v2 node/tool evidence.",
            "inputSchema": _object(_with_context({"repo_path": s, "tool_name": s, "arguments": obj, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300}}), ["tool_name"]),
        },
        {
            "name": "case_prepare_plan",
            "description": "Runtime-owned preflight for one frozen Case. Reports required field capabilities and DB Human Gate exposure without executing providers or constructing data. Must run on the active EXECUTION task.",
            "inputSchema": _object(_with_context({"case": obj, "attempt_id": s, "target_id": s}), ["case", "attempt_id", "target_id", "mission_context"]),
        },
        {
            "name": "case_prepare_execute",
            "description": "Runtime-owned Case preparation. RC7 itself invokes configured precondition/data providers, hashes responses, persists R1 evidence, and returns PREPARED only after verification. DB_CREATE cannot run without a trusted Human Gate approval outside the Agent MCP surface.",
            "inputSchema": _object(_with_context({"case": obj, "attempt_id": s, "target_id": s}), ["case", "attempt_id", "target_id", "mission_context"]),
        },
    ]


def _text(value: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}]}


def _rc7_runtime_status() -> Dict[str, Any]:
    base = dict(rc6._runtime_status())
    base.update({
        "server": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "rc7_truth_overlay": True,
        "canonical_r1_path": str(rc6._state_root() / "r1" / "event-stream.jsonl"),
        "node_tool_conformance": "DURABLE_R1_CALL_EVIDENCE",
        "case_preparation_runtime": "TRUSTED_PROVIDER_EXECUTION_AND_HUMAN_GATE",
    })
    return base


def _pop_context(arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
    clean = dict(arguments or {})
    raw = clean.pop("mission_context", None)
    if raw is None:
        return clean, None
    if not isinstance(raw, dict):
        raise RuntimeError("MISSION_CONTEXT_MUST_BE_OBJECT")
    context = {
        "mission_id": str(raw.get("mission_id") or "").strip(),
        "task_id": str(raw.get("task_id") or "").strip(),
        "worker_id": str(raw.get("worker_id") or "").strip(),
    }
    if not all(context.values()):
        raise RuntimeError("MISSION_CONTEXT_FIELDS_REQUIRED")
    worker_arg = str(clean.get("worker_id") or "").strip()
    if worker_arg and worker_arg != context["worker_id"]:
        raise RuntimeError("MISSION_CONTEXT_WORKER_ARGUMENT_MISMATCH")
    validate_call_context(rc6._truth_runtime(), **context)
    return clean, context


def _record_tool_call(name: str, context: Optional[Dict[str, str]], result: object) -> None:
    if context is None:
        return
    truth = rc6._truth_runtime()
    if not contract_enabled(truth, context["mission_id"]):
        return
    record_successful_call(truth, mission_id=context["mission_id"], task_id=context["task_id"], worker_id=context["worker_id"], tool_name=name, result=result)


def _case_service() -> CasePreparationService:
    return CasePreparationService(rc6._truth_runtime(), rc6._state_root())


def _invoke_extra(name: str, arguments: Dict[str, Any], context: Optional[Dict[str, str]] = None) -> object:
    if name == "read_text":
        return read_text(path=arguments["path"], scope=str(arguments.get("scope") or "workspace"), max_chars=int(arguments.get("max_chars", 200000)))
    if name == "git_show_revision":
        return git_show_revision(repo_path=str(arguments.get("repo_path") or "."), ref=str(arguments.get("ref") or "HEAD"))
    if name == "git_diff":
        return git_diff(repo_path=str(arguments.get("repo_path") or "."), base_ref=arguments["base_ref"], head_ref=arguments["head_ref"], paths=arguments.get("paths") or (), max_chars=int(arguments.get("max_chars", 200000)))
    if name == "codegraph_probe":
        return codegraph_probe(repo_path=str(arguments.get("repo_path") or "."))
    if name == "codegraph_query":
        return codegraph_query(args=arguments["args"], repo_path=str(arguments.get("repo_path") or "."), timeout_seconds=int(arguments.get("timeout_seconds", 60)), max_chars=int(arguments.get("max_chars", 200000)))
    if name == "codegraph_mcp_tools":
        return list_codegraph_tools(repo_path=str(arguments.get("repo_path") or "."), timeout_seconds=int(arguments.get("timeout_seconds", 30)))
    if name == "codegraph_mcp_call":
        return call_codegraph_tool(tool_name=arguments["tool_name"], arguments=arguments.get("arguments") or {}, repo_path=str(arguments.get("repo_path") or "."), timeout_seconds=int(arguments.get("timeout_seconds", 60)))
    if name in {"case_prepare_plan", "case_prepare_execute"}:
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_CASE_PREPARATION")
        service = _case_service()
        payload = {
            "mission_id": context["mission_id"],
            "task_id": context["task_id"],
            "worker_id": context["worker_id"],
            "case": arguments["case"],
            "attempt_id": arguments["attempt_id"],
            "target_id": arguments["target_id"],
        }
        return service.plan(**payload) if name == "case_prepare_plan" else service.prepare(**payload)
    raise RuntimeError("RC7_EXTRA_TOOL_UNKNOWN:%s" % name)


def _response_is_error(response: object) -> bool:
    if not isinstance(response, dict):
        return True
    if "error" in response:
        return True
    result = response.get("result")
    return isinstance(result, dict) and bool(result.get("isError"))


def _augment_base_tool_schemas(tools):
    context_schema = _mission_context_schema()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("name") not in _TRACKED_BASE_TOOLS:
            continue
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            continue
        properties = schema.setdefault("properties", {})
        if isinstance(properties, dict):
            properties.setdefault("mission_context", context_schema)
        description = str(tool.get("description") or "")
        if "mission_context" not in description:
            tool["description"] = description + " Supply mission_context for durable graph-v2 node/tool evidence."
        if tool.get("name") == "runner_execute":
            tool["description"] += " For a contracted RC7 Mission, prepared_attempt must exactly match durable CASE_PREPARED_ATTEMPT R1 evidence produced by case_prepare_execute."
    return tools


def _call_base_with_context(message: Dict[str, Any], name: str) -> Dict[str, Any]:
    forwarded = copy.deepcopy(message)
    params = forwarded.setdefault("params", {})
    clean, context = _pop_context(params.get("arguments") or {})
    if name == "runner_execute" and context is not None and contract_enabled(rc6._truth_runtime(), context["mission_id"]):
        prepared = clean.get("prepared_attempt")
        if not isinstance(prepared, dict):
            raise RuntimeError("DURABLE_PREPARED_ATTEMPT_REQUIRED")
        _case_service().require_prepared(mission_id=context["mission_id"], task_id=context["task_id"], prepared_attempt=prepared)
    params["arguments"] = clean
    response = rc6.handle(forwarded)
    if context is not None and not _response_is_error(response):
        _record_tool_call(name, context, response)
    return response


def handle(message: Dict[str, Any]):
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        response = rc6.handle(message)
        if isinstance(response, dict) and isinstance(response.get("result"), dict):
            response["result"]["serverInfo"] = {"name": SERVER_NAME, "version": SERVER_VERSION}
            response["result"]["instructions"] = (
                "RC7 closed-loop testing control plane. RC6 governed tools remain available. "
                "RC7 durable control entities use the canonical R1 Event Stream. read_text and Git/CodeGraph "
                "tools are real read-only execution. Graph-v2 producer calls should carry mission_context so "
                "successful calls become NODE_TOOL_CALL evidence. Case preparation is runtime-owned: Agents "
                "request case_prepare_execute, but RC7 itself invokes field providers and DB_CREATE requires a "
                "trusted Human Gate approval outside the Agent MCP surface. runner_execute rejects fabricated "
                "prepared_attempt payloads. Workers never own PASS authority."
            )
        return response
    if method == "tools/list":
        base = rc6.handle(message)
        if not isinstance(base, dict):
            raise RuntimeError("RC6_TOOL_LIST_INVALID")
        result = base.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("RC6_TOOL_LIST_INVALID")
        tools = list(result["tools"])
        for tool in tools:
            if isinstance(tool, dict) and tool.get("name") == "runtime_status":
                tool["description"] = "Read RC7 runtime/build identity and canonical R1 wiring."
        result["tools"] = _augment_base_tool_schemas(tools) + _extra_tools()
        return base
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        if name == "runtime_status":
            return {"jsonrpc": "2.0", "id": msg_id, "result": _text(_rc7_runtime_status())}
        if name in _TRACKED_BASE_TOOLS:
            try:
                return _call_base_with_context(message, name)
            except Exception as exc:
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
        if any(tool["name"] == name for tool in _extra_tools()):
            try:
                clean, context = _pop_context(params.get("arguments") or {})
                raw_result = _invoke_extra(name, clean, context)
                if name not in {"case_prepare_plan", "case_prepare_execute"}:
                    _record_tool_call(name, context, raw_result)
                return {"jsonrpc": "2.0", "id": msg_id, "result": _text(raw_result)}
            except Exception as exc:
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
    return rc6.handle(message)


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
