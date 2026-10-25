from __future__ import annotations

import copy
import json
import os
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
from rc7_runtime.real_executor_provenance import record_successful_execution_invocation
from rc7_runtime.truth_overlay import install_rc7_truth_overlay
from .browser_executor import execute_browser_action
from .codegraph_mcp import call_codegraph_tool, list_codegraph_tools
from .contracted_runner import execute_contracted_runner
from .database_executor import execute_database_sql
from .e2e_executor import execute_e2e_journey
from .k6_executor import execute_k6_scenario
from .professional_tools import codegraph_probe, codegraph_query, git_diff, git_show_revision
from .source_tools import read_text
from .zap_executor import execute_zap_scan


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
        {
            "name": "database_execute",
            "description": "Execute L2 SQL only through the runtime-configured real database client. SQL is sent on stdin with shell disabled. PFC_DB_TARGET_ID must exactly match the current Attempt target. Only after a successful external call does MCP emit current-attempt REAL_EXECUTOR_INVOCATION evidence; failures never emit success provenance.",
            "inputSchema": _object(
                _with_context({
                    "sql": {"type": "string", "minLength": 1},
                    "attempt_id": {"type": "string", "minLength": 1},
                    "target_id": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                }),
                ["sql", "attempt_id", "target_id", "mission_context"],
            ),
        },
        {
            "name": "browser_execute",
            "description": "Execute L4 UI/browser actions only through the runtime-configured real BrowserSkill/Playwright client. Request JSON is sent on stdin with shell disabled. PFC_BROWSER_TARGET_ID must exactly match the current Attempt target. Only after a successful external call does MCP emit current-attempt REAL_EXECUTOR_INVOCATION evidence; failures never emit success provenance.",
            "inputSchema": _object(
                _with_context({
                    "request": obj,
                    "attempt_id": {"type": "string", "minLength": 1},
                    "target_id": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                }),
                ["request", "attempt_id", "target_id", "mission_context"],
            ),
        },
        {
            "name": "e2e_execute",
            "description": "Execute L5 only through the runtime-configured cross-system E2E orchestrator. A zero process exit is insufficient: its stdout JSON receipt must prove at least two distinct successful system hops plus a PASS final Oracle, with non-fixture invocation/evidence refs and exact target binding. Only then does MCP emit current-attempt e2e-orchestrator provenance.",
            "inputSchema": _object(
                _with_context({
                    "journey": obj,
                    "attempt_id": {"type": "string", "minLength": 1},
                    "target_id": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                }),
                ["journey", "attempt_id", "target_id", "mission_context"],
            ),
        },
        {
            "name": "k6_execute",
            "description": "Execute L6 only through the configured k6 CLI. The script must be workspace-contained and PFC_K6_TARGET_ID must match the Attempt target. A zero process exit is insufficient: --summary-export must prove iterations > 0 and at least one evaluated threshold, with every threshold PASS. Only then does MCP emit current-attempt k6 provenance.",
            "inputSchema": _object(
                _with_context({
                    "script_path": {"type": "string", "minLength": 1},
                    "scenario_id": {"type": "string", "minLength": 1},
                    "attempt_id": {"type": "string", "minLength": 1},
                    "target_id": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 7200},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                }),
                ["script_path", "scenario_id", "attempt_id", "target_id", "mission_context"],
            ),
        },
        {
            "name": "zap_execute",
            "description": "Execute L7 only through the configured ZAP Automation Framework client. The plan must be workspace-contained, target identity and target URL must be exact, and the process must generate a fresh JSON report containing the configured target site. Security findings are Actual, not executor failure; only invalid/missing execution evidence blocks provenance. After report validation MCP emits current-attempt zap provenance.",
            "inputSchema": _object(
                _with_context({
                    "plan_path": {"type": "string", "minLength": 1},
                    "scan_id": {"type": "string", "minLength": 1},
                    "attempt_id": {"type": "string", "minLength": 1},
                    "target_id": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 7200},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 1000000},
                }),
                ["plan_path", "scan_id", "attempt_id", "target_id", "mission_context"],
            ),
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
        "execution_oracle_runtime": "RC7_DETERMINISTIC_ACTUAL_PATH_OPERATOR_EXPECTED",
        "l2_database_executor": "CAPABILITY_CONFIGURED_REAL_PROCESS_WITH_ATTEMPT_PROVENANCE",
        "l4_browser_executor": "CAPABILITY_CONFIGURED_REAL_PROCESS_WITH_ATTEMPT_PROVENANCE",
        "l5_e2e_executor": "RECEIPT_VALIDATED_CROSS_SYSTEM_PROCESS_WITH_ATTEMPT_PROVENANCE",
        "l6_k6_executor": "SUMMARY_AND_THRESHOLD_VALIDATED_K6_WITH_ATTEMPT_PROVENANCE",
        "l7_zap_executor": "FRESH_TARGET_REPORT_VALIDATED_ZAP_WITH_ATTEMPT_PROVENANCE",
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


def _require_execution_task(context: Mapping[str, str], *, prefix: str = "EXECUTION") -> None:
    rows = rc6._truth_runtime().query("rc7_task", task_id=context["task_id"])
    if len(rows) != 1:
        raise RuntimeError("%s_TASK_NOT_UNIQUE" % prefix)
    row = rows[0]
    if str(row.get("mission_id") or "") != context["mission_id"]:
        raise RuntimeError("%s_TASK_MISSION_MISMATCH" % prefix)
    if str(row.get("node") or "") != "EXECUTION":
        raise RuntimeError("%s_REQUIRES_EXECUTION_TASK" % prefix)


def _require_database_target(target_id: object) -> str:
    target = str(target_id or "").strip()
    if not target:
        raise RuntimeError("DATABASE_TARGET_ID_REQUIRED")
    configured = str(os.environ.get("PFC_DB_TARGET_ID") or "").strip()
    if not configured:
        raise RuntimeError("DATABASE_TARGET_NOT_CONFIGURED")
    if configured != target:
        raise RuntimeError("DATABASE_TARGET_MISMATCH")
    return target


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
    if name == "database_execute":
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_DATABASE_EXECUTION")
        _require_execution_task(context, prefix="DATABASE_EXECUTION")
        target_id = _require_database_target(arguments.get("target_id"))
        result = execute_database_sql(
            sql=arguments["sql"],
            target_id=target_id,
            timeout_seconds=int(arguments.get("timeout_seconds", 60)),
            max_chars=int(arguments.get("max_chars", 200000)),
        )
        evidence = record_successful_execution_invocation(
            rc6._truth_runtime(),
            evidence_root=str(rc6._state_root() / "evidence"),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            attempt_id=str(arguments["attempt_id"]),
            runtime_worker_id=context["worker_id"],
            layer="L2",
            target_id=target_id,
            tool_name="database",
            invocation_ref=str(result["invocation_ref"]),
            result=result,
        )
        response = dict(result)
        response["provenance_evidence_id"] = evidence.evidence_id
        return response
    if name == "browser_execute":
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_BROWSER_EXECUTION")
        _require_execution_task(context, prefix="BROWSER_EXECUTION")
        target_id = str(arguments.get("target_id") or "").strip()
        if not target_id:
            raise RuntimeError("BROWSER_TARGET_ID_REQUIRED")
        result = execute_browser_action(
            request=arguments["request"],
            target_id=target_id,
            timeout_seconds=int(arguments.get("timeout_seconds", 120)),
            max_chars=int(arguments.get("max_chars", 200000)),
        )
        evidence = record_successful_execution_invocation(
            rc6._truth_runtime(),
            evidence_root=str(rc6._state_root() / "evidence"),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            attempt_id=str(arguments["attempt_id"]),
            runtime_worker_id=context["worker_id"],
            layer="L4",
            target_id=target_id,
            tool_name="browser-skill",
            invocation_ref=str(result["invocation_ref"]),
            result=result,
        )
        response = dict(result)
        response["provenance_evidence_id"] = evidence.evidence_id
        return response
    if name == "e2e_execute":
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_E2E_EXECUTION")
        _require_execution_task(context, prefix="E2E_EXECUTION")
        target_id = str(arguments.get("target_id") or "").strip()
        if not target_id:
            raise RuntimeError("E2E_TARGET_ID_REQUIRED")
        result = execute_e2e_journey(
            journey=arguments["journey"],
            target_id=target_id,
            timeout_seconds=int(arguments.get("timeout_seconds", 300)),
            max_chars=int(arguments.get("max_chars", 200000)),
        )
        evidence = record_successful_execution_invocation(
            rc6._truth_runtime(),
            evidence_root=str(rc6._state_root() / "evidence"),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            attempt_id=str(arguments["attempt_id"]),
            runtime_worker_id=context["worker_id"],
            layer="L5",
            target_id=target_id,
            tool_name="e2e-orchestrator",
            invocation_ref=str(result["invocation_ref"]),
            result=result,
        )
        response = dict(result)
        response["provenance_evidence_id"] = evidence.evidence_id
        return response
    if name == "k6_execute":
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_K6_EXECUTION")
        _require_execution_task(context, prefix="K6_EXECUTION")
        target_id = str(arguments.get("target_id") or "").strip()
        if not target_id:
            raise RuntimeError("K6_TARGET_ID_REQUIRED")
        result = execute_k6_scenario(
            script_path=str(arguments["script_path"]),
            scenario_id=str(arguments["scenario_id"]),
            target_id=target_id,
            timeout_seconds=int(arguments.get("timeout_seconds", 900)),
            max_chars=int(arguments.get("max_chars", 200000)),
        )
        evidence = record_successful_execution_invocation(
            rc6._truth_runtime(),
            evidence_root=str(rc6._state_root() / "evidence"),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            attempt_id=str(arguments["attempt_id"]),
            runtime_worker_id=context["worker_id"],
            layer="L6",
            target_id=target_id,
            tool_name="k6",
            invocation_ref=str(result["invocation_ref"]),
            result=result,
        )
        response = dict(result)
        response["provenance_evidence_id"] = evidence.evidence_id
        return response
    if name == "zap_execute":
        if context is None:
            raise RuntimeError("MISSION_CONTEXT_REQUIRED_FOR_ZAP_EXECUTION")
        _require_execution_task(context, prefix="ZAP_EXECUTION")
        target_id = str(arguments.get("target_id") or "").strip()
        if not target_id:
            raise RuntimeError("ZAP_TARGET_ID_REQUIRED")
        result = execute_zap_scan(
            plan_path=str(arguments["plan_path"]),
            scan_id=str(arguments["scan_id"]),
            target_id=target_id,
            timeout_seconds=int(arguments.get("timeout_seconds", 1800)),
            max_chars=int(arguments.get("max_chars", 200000)),
        )
        evidence = record_successful_execution_invocation(
            rc6._truth_runtime(),
            evidence_root=str(rc6._state_root() / "evidence"),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            attempt_id=str(arguments["attempt_id"]),
            runtime_worker_id=context["worker_id"],
            layer="L7",
            target_id=target_id,
            tool_name="zap",
            invocation_ref=str(result["invocation_ref"]),
            result=result,
        )
        response = dict(result)
        response["provenance_evidence_id"] = evidence.evidence_id
        return response
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
            tool["description"] += " For a contracted RC7 Mission, prepared_attempt must exactly match durable CASE_PREPARED_ATTEMPT R1 evidence produced by case_prepare_execute and Oracle evaluation is runtime-owned/deterministic."
    return tools


def _call_base_with_context(message: Dict[str, Any], name: str) -> Dict[str, Any]:
    forwarded = copy.deepcopy(message)
    params = forwarded.setdefault("params", {})
    clean, context = _pop_context(params.get("arguments") or {})
    contracted_runner = (
        name == "runner_execute"
        and context is not None
        and contract_enabled(rc6._truth_runtime(), context["mission_id"])
    )
    if contracted_runner:
        prepared = clean.get("prepared_attempt")
        if not isinstance(prepared, dict):
            raise RuntimeError("DURABLE_PREPARED_ATTEMPT_REQUIRED")
        _case_service().require_prepared(
            mission_id=context["mission_id"],
            task_id=context["task_id"],
            prepared_attempt=prepared,
        )
        raw_result = execute_contracted_runner(
            clean,
            authority=rc6._authority_runtime(),
            truth=rc6._truth_runtime(),
            broker=rc6._capability_broker(),
            state_root=rc6._state_root(),
            mission_id=context["mission_id"],
            task_id=context["task_id"],
        )
        response = {
            "jsonrpc": "2.0",
            "id": forwarded.get("id"),
            "result": _text(raw_result),
        }
    else:
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
                "trusted Human Gate approval outside the Agent MCP surface. L2 database_execute is runtime-owned: "
                "it invokes the configured real DB client with SQL on stdin, requires exact target binding, and "
                "only after success emits current-attempt REAL_EXECUTOR_INVOCATION evidence. L4 browser_execute "
                "likewise invokes only the configured BrowserSkill/Playwright process with canonical JSON on stdin, "
                "requires exact target binding, and emits trusted current-attempt provenance only after success. "
                "L5 e2e_execute additionally requires a receipt proving at least two distinct successful system hops "
                "and a PASS final Oracle before e2e-orchestrator provenance can be emitted. L6 k6_execute requires "
                "workspace-contained scripts plus a k6 summary proving iterations > 0 and all evaluated thresholds "
                "PASS before k6 provenance can be emitted. L7 zap_execute requires a fresh target-matching ZAP report; "
                "security findings remain product Actual rather than executor failure. runner_execute rejects fabricated "
                "prepared_attempt payloads and contracted Missions use the RC7 deterministic Oracle. Workers never own PASS authority."
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
                if name not in {"case_prepare_plan", "case_prepare_execute", "database_execute", "browser_execute", "e2e_execute", "k6_execute", "zap_execute"}:
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
