from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from rc6_runtime import (
    AutonomousMissionOrchestrator,
    AuthorityRuntime,
    BankRealityRegistry,
    MissionRuntime,
    TargetIdentityBuilder,
    ToolCapabilityBroker,
    TruthRuntime,
)
from .execution_closure_mcp import call_execution_closure_tool, execution_closure_tool_schemas

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "pfc-aitest-rc6"
SERVER_VERSION = "6.1-execution-closure-engineering-candidate"

_AUTH_EVENT = {
    "test_intent": "TEST_INTENT_UPSERTED",
    "test_condition": "TEST_CONDITION_UPSERTED",
    "requirement_analysis": "REQUIREMENT_ANALYSIS_UPSERTED",
    "code_analysis": "CODE_ANALYSIS_UPSERTED",
    "case_candidate_l1": "TEST_CASE_UPSERTED",
    "case_candidate_l2": "TEST_CASE_UPSERTED",
    "case_candidate_l3": "TEST_CASE_UPSERTED",
    "case_candidate_l4": "TEST_CASE_UPSERTED",
    "case_candidate_l5": "TEST_CASE_UPSERTED",
    "case_candidate_l6": "TEST_CASE_UPSERTED",
    "case_candidate_l7": "TEST_CASE_UPSERTED",
    "execution_attempt": "EXECUTION_ATTEMPT_UPSERTED",
    "assertion": "ASSERTION_UPSERTED",
    "evidence": "EVIDENCE_UPSERTED",
    "defect": "DEFECT_UPSERTED",
    "coverage_observation": "COVERAGE_OBSERVATION_UPSERTED",
    "executable_test_spec": "EXECUTABLE_TEST_SPEC_UPSERTED",
    "automation_mapping": "AUTOMATION_MAPPING_UPSERTED",
    "script_artifact": "SCRIPT_ARTIFACT_UPSERTED",
    "script_validation": "SCRIPT_VALIDATION_UPSERTED",
    "failure_diagnosis": "FAILURE_DIAGNOSIS_UPSERTED",
    "root_cause_candidate": "ROOT_CAUSE_CANDIDATE_UPSERTED",
    "recovery_decision": "RECOVERY_DECISION_UPSERTED",
    "recovery_action": "RECOVERY_ACTION_UPSERTED",
    "execution_convergence": "EXECUTION_CONVERGENCE_UPSERTED",
}

_runtime_key: Optional[str] = None
_authority: Optional[AuthorityRuntime] = None
_capabilities: Optional[ToolCapabilityBroker] = None


def _home() -> Path:
    return Path(os.environ.get("PFC_AITEST_HOME", os.getcwd())).resolve()


def _state_root() -> Path:
    root = Path(os.environ.get("PFC_AITEST_STATE_DIR", str(_home() / "runtime-state"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _mission_runtime() -> MissionRuntime:
    return MissionRuntime(str(_state_root() / "missions"))


def _truth_runtime() -> TruthRuntime:
    return TruthRuntime(_state_root() / "r1" / "event-stream.jsonl")


def _orchestrator() -> AutonomousMissionOrchestrator:
    return AutonomousMissionOrchestrator(_mission_runtime(), _truth_runtime())


def _reality_registry() -> BankRealityRegistry:
    return BankRealityRegistry(_state_root() / "bank-reality.json")


def _authority_runtime() -> AuthorityRuntime:
    global _runtime_key, _authority
    root = _state_root()
    key_id = str(root)
    if _authority is None or _runtime_key != key_id:
        key_path = root / "control" / "authority.key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(secrets.token_bytes(32))
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        key = key_path.read_bytes()
        _authority = AuthorityRuntime(key)
        _runtime_key = key_id
    return _authority


def _capability_broker() -> ToolCapabilityBroker:
    global _capabilities, _runtime_key
    root = _state_root()
    key_id = str(root)
    if _capabilities is None or _runtime_key != key_id:
        _capabilities = ToolCapabilityBroker()
        _runtime_key = key_id
    return _capabilities


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


def _text(value: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(_plain(value), ensure_ascii=False, sort_keys=True)}]}


def _object(properties: dict, required: list[str] | None = None, *, additional: bool = False) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": additional}


def _tools() -> list[dict]:
    s = {"type": "string"}
    a = {"type": "array", "items": s}
    o = {"type": "object", "additionalProperties": True}
    core = [
        {"name": "runtime_status", "description": "Read RC6 runtime/build identity.", "inputSchema": _object({})},
        {"name": "mission_create", "description": "Create one durable Mission.", "inputSchema": _object({"mission_id": s, "release_id": s}, ["mission_id", "release_id"])},
        {"name": "mission_status", "description": "Read durable Mission state.", "inputSchema": _object({"mission_id": s}, ["mission_id"])},
        {"name": "mission_checkpoint", "description": "Create bounded ResumeEnvelope without chat history.", "inputSchema": _object({"mission_id": s}, ["mission_id"])},
        {"name": "mission_plan_next", "description": "Read the deterministic next legal Mission directive without changing professional truth.", "inputSchema": _object({"mission_id": s, "context_pressure": {"type": "boolean"}}, ["mission_id"])},
        {"name": "mission_control_tick", "description": "Advance at most one legal Stage or checkpoint/rotate, then return the next deterministic directive.", "inputSchema": _object({"mission_id": s, "context_pressure": {"type": "boolean"}}, ["mission_id"])},
        {"name": "mission_gate_commit", "description": "Commit a PASS only from a deterministic runtime gate result with an evidence reference; Stage mismatch fails closed.", "inputSchema": _object({"mission_id": s, "gate_name": s, "evidence_ref": s}, ["mission_id", "gate_name", "evidence_ref"])},
        {"name": "mission_gate_block", "description": "Record a deterministic gate block/gap and prevent Stage advancement.", "inputSchema": _object({"mission_id": s, "gate_name": s, "reason": s}, ["mission_id", "gate_name", "reason"])},
        {"name": "mission_bind_target", "description": "Bind the exact TargetIdentity to the durable Mission before preparation/execution.", "inputSchema": _object({"mission_id": s, "target_id": s}, ["mission_id", "target_id"])},
        {"name": "worker_issue", "description": "Issue immutable runtime WorkerIdentity.", "inputSchema": _object({"role": s, "phase": s, "layer": {"type": ["string", "null"]}, "generation": {"type": "integer", "minimum": 0}, "session_id": s}, ["role", "phase", "generation", "session_id"])},
        {"name": "worker_rotate", "description": "Rotate only to the same role/layer in a successor session.", "inputSchema": _object({"worker_id": s, "successor_session_id": s}, ["worker_id", "successor_session_id"])},
        {"name": "lease_issue", "description": "Issue signed scope/artifact/tool lease.", "inputSchema": _object({"worker_id": s, "scope_ref": s, "allowed_artifact_types": a, "allowed_tools": a, "ttl_seconds": {"type": "integer", "minimum": 1}}, ["worker_id", "scope_ref", "allowed_artifact_types", "allowed_tools"])},
        {"name": "tool_authorize", "description": "Fail-closed lease tool authorization before a professional tool call.", "inputSchema": _object({"worker_id": s, "lease_id": s, "tool_name": s}, ["worker_id", "lease_id", "tool_name"])},
        {"name": "artifact_record", "description": "Authorize role+lease then atomically append one canonical R1 artifact with read-after-write integrity.", "inputSchema": _object({"worker_id": s, "lease_id": s, "authorization_artifact_type": s, "payload": o}, ["worker_id", "lease_id", "authorization_artifact_type", "payload"])},
        {"name": "truth_inventory", "description": "Read R1 projection inventory.", "inputSchema": _object({})},
        {"name": "truth_query", "description": "Query a bounded R1 projection by canonical top-level filters.", "inputSchema": _object({"artifact_type": s, "filters": o, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, ["artifact_type"])},
        {"name": "reality_list", "description": "List Bank Reality facts; values are references, never secrets.", "inputSchema": _object({"kind": {"type": ["string", "null"]}})},
        {"name": "reality_get", "description": "Get one Bank Reality fact.", "inputSchema": _object({"kind": s, "fact_id": s}, ["kind", "fact_id"])},
        {"name": "reality_upsert", "description": "Upsert canonical Bank Reality fact; plaintext secret fields are rejected by runtime.", "inputSchema": _object({"kind": s, "fact_id": s, "attributes": o, "status": s}, ["kind", "fact_id", "attributes", "status"])},
        {"name": "reality_reconcile", "description": "Freshness reconcile one fact against observed reality.", "inputSchema": _object({"kind": s, "fact_id": s, "observed": o, "verified_at": {"type": ["string", "null"]}}, ["kind", "fact_id", "observed"])},
        {"name": "target_build", "description": "Build deterministic TargetIdentity; any stale/unbound fact fails closed.", "inputSchema": _object({"release_id": s, "deployment_mode": s, "environment_fact_id": s, "repository_fact_ids": o, "frontend_route_fact_id": s, "gateway_route_fact_id": s, "database_fact_ids": o, "auth_fact_id": s, "cat_fact_id": s, "account_fact_id": s}, ["release_id", "deployment_mode", "environment_fact_id", "repository_fact_ids", "frontend_route_fact_id", "gateway_route_fact_id", "database_fact_ids", "auth_fact_id", "cat_fact_id", "account_fact_id"])},
        {"name": "capability_discover", "description": "Record tool discovery only; this does not mean READY.", "inputSchema": _object({"tool_id": s, "location": s}, ["tool_id", "location"])},
        {"name": "capability_mark_executable", "description": "Record executable binding.", "inputSchema": _object({"tool_id": s, "exec_ref": s}, ["tool_id", "exec_ref"])},
        {"name": "capability_register", "description": "Record DSH/MCP/native tool registration.", "inputSchema": _object({"tool_id": s, "registration_ref": s}, ["tool_id", "registration_ref"])},
        {"name": "capability_bind_worker", "description": "Bind exact Worker visibility and permission.", "inputSchema": _object({"tool_id": s, "worker_id": s, "visible": {"type": "boolean"}, "permitted": {"type": "boolean"}}, ["tool_id", "worker_id", "visible", "permitted"])},
        {"name": "capability_record_probe", "description": "Record real health probe with tool-call and evidence refs.", "inputSchema": _object({"tool_id": s, "success": {"type": "boolean"}, "tool_call_ref": {"type": ["string", "null"]}, "evidence_ref": {"type": ["string", "null"]}}, ["tool_id", "success"])},
        {"name": "capability_target_ready", "description": "Bind tool readiness to exact TargetIdentity with evidence.", "inputSchema": _object({"tool_id": s, "target_id": s, "evidence_ref": s}, ["tool_id", "target_id", "evidence_ref"])},
        {"name": "capability_admit", "description": "Fail-closed admission for exact worker/tool set/target.", "inputSchema": _object({"worker_id": s, "required_tools": a, "target_id": s}, ["worker_id", "required_tools", "target_id"])},
        {"name": "capability_record_call", "description": "Record a real admitted professional tool call as provenance.", "inputSchema": _object({"tool_id": s, "worker_id": s, "target_id": s, "call_ref": s, "evidence_ref": s}, ["tool_id", "worker_id", "target_id", "call_ref", "evidence_ref"])},
    ]
    return core + execution_closure_tool_schemas()


def _runtime_status() -> dict:
    home = _home()
    def read(name: str) -> str | None:
        path = home / name
        return path.read_text(encoding="utf-8").strip() if path.is_file() else None
    return {
        "server": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "release_status": read("RELEASE_STATUS") or "SOURCE_TREE",
        "build_id": read("BUILD_ID"),
        "source_commit": read("SOURCE_COMMIT"),
        "durable_truth": "R1_EVENT_STREAM",
        "mission_session_separated": True,
        "autonomous_orchestrator": True,
        "execution_closure_overlay": True,
        "governed_control_tools": len(_tools()),
    }


def _call_tool(name: str, arguments: dict) -> dict:
    if name == "runtime_status":
        return _text(_runtime_status())
    if name == "mission_create":
        return _text(_mission_runtime().create(arguments["mission_id"], arguments["release_id"]))
    if name == "mission_status":
        return _text(_mission_runtime().load(arguments["mission_id"]))
    if name == "mission_checkpoint":
        rt = _mission_runtime(); return _text(rt.checkpoint(rt.load(arguments["mission_id"])))
    if name == "mission_plan_next":
        return _text(_orchestrator().plan_next(arguments["mission_id"], context_pressure=bool(arguments.get("context_pressure", False))))
    if name == "mission_control_tick":
        return _text(_orchestrator().control_tick(arguments["mission_id"], context_pressure=bool(arguments.get("context_pressure", False))))
    if name == "mission_gate_commit":
        return _text(_orchestrator().record_verified_gate(arguments["mission_id"], arguments["gate_name"], arguments["evidence_ref"]))
    if name == "mission_gate_block":
        return _text(_orchestrator().record_gate_blocked(arguments["mission_id"], arguments["gate_name"], arguments["reason"]))
    if name == "mission_bind_target":
        return _text(_orchestrator().bind_target(arguments["mission_id"], arguments["target_id"]))
    if name == "worker_issue":
        return _text(_authority_runtime().issue_identity(arguments["role"], arguments["phase"], arguments.get("layer"), int(arguments["generation"]), arguments["session_id"]))
    if name == "worker_rotate":
        return _text(_authority_runtime().rotate_same_role(arguments["worker_id"], arguments["successor_session_id"]))
    if name == "lease_issue":
        return _text(_authority_runtime().issue_lease(arguments["worker_id"], arguments["scope_ref"], arguments["allowed_artifact_types"], arguments["allowed_tools"], int(arguments.get("ttl_seconds", 1800))))
    if name == "tool_authorize":
        _authority_runtime().authorize_tool(arguments["worker_id"], arguments["lease_id"], arguments["tool_name"]); return _text({"status": "AUTHORIZED"})
    if name == "artifact_record":
        auth_type = arguments["authorization_artifact_type"]
        event_type = _AUTH_EVENT.get(auth_type)
        if event_type is None:
            raise RuntimeError("AUTH_ARTIFACT_NOT_R1_RECORDABLE")
        _authority_runtime().authorize_artifact(arguments["worker_id"], arguments["lease_id"], auth_type)
        payload = arguments["payload"]
        if auth_type.startswith("case_candidate_l"):
            expected_layer = auth_type.rsplit("_", 1)[-1].upper()
            if payload.get("layer") != expected_layer:
                raise RuntimeError("CASE_LAYER_AUTHORITY_MISMATCH")
        return _text(_truth_runtime().append_atomic(event_type, payload))
    if name == "truth_inventory":
        return _text(_truth_runtime().full_inventory())
    if name == "truth_query":
        rows = _truth_runtime().query(arguments["artifact_type"], **(arguments.get("filters") or {}))
        return _text({"items": rows[: int(arguments.get("limit", 100))], "total": len(rows)})
    if name == "reality_list":
        return _text(_reality_registry().list(arguments.get("kind")))
    if name == "reality_get":
        return _text(_reality_registry().get(arguments["kind"], arguments["fact_id"]))
    if name == "reality_upsert":
        return _text(_reality_registry().upsert(arguments["kind"], arguments["fact_id"], arguments["attributes"], status=arguments["status"]))
    if name == "reality_reconcile":
        return _text(_reality_registry().reconcile(arguments["kind"], arguments["fact_id"], arguments["observed"], verified_at=arguments.get("verified_at")))
    if name == "target_build":
        return _text(TargetIdentityBuilder(_reality_registry()).build(**arguments))

    closure = call_execution_closure_tool(
        name,
        arguments,
        authority=_authority_runtime(),
        truth=_truth_runtime(),
        broker=_capability_broker(),
        state_root=_state_root(),
    )
    if closure is not None:
        return _text(closure)

    broker = _capability_broker()
    if name == "capability_discover":
        broker.discover(arguments["tool_id"], arguments["location"]); return _text(broker.readiness(arguments["tool_id"], "__unbound__", "__unbound__"))
    if name == "capability_mark_executable":
        broker.mark_executable(arguments["tool_id"], arguments["exec_ref"]); return _text({"status": "RECORDED"})
    if name == "capability_register":
        broker.register(arguments["tool_id"], arguments["registration_ref"]); return _text({"status": "RECORDED"})
    if name == "capability_bind_worker":
        broker.bind_worker(arguments["tool_id"], arguments["worker_id"], visible=arguments["visible"], permitted=arguments["permitted"]); return _text({"status": "RECORDED"})
    if name == "capability_record_probe":
        broker.record_probe(arguments["tool_id"], success=arguments["success"], tool_call_ref=arguments.get("tool_call_ref"), evidence_ref=arguments.get("evidence_ref")); return _text({"status": "RECORDED"})
    if name == "capability_target_ready":
        broker.mark_target_ready(arguments["tool_id"], arguments["target_id"], arguments["evidence_ref"]); return _text({"status": "RECORDED"})
    if name == "capability_admit":
        return _text(broker.admit(arguments["worker_id"], arguments["required_tools"], arguments["target_id"]))
    if name == "capability_record_call":
        return _text(broker.record_tool_call(arguments["tool_id"], worker_id=arguments["worker_id"], target_id=arguments["target_id"], call_ref=arguments["call_ref"], evidence_ref=arguments["evidence_ref"]))
    raise RuntimeError("UNKNOWN_TOOL")


def handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": message.get("params", {}).get("protocolVersion") or PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}, "instructions": "RC6 autonomous governed control plane. Runtime chooses the next legal Mission directive; chat text is never Mission truth. Execution Closure requires immutable ExecutableSpec, SCRIPT_READY, real RunnerAdapter evidence and evidence-backed recovery."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tools()}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = _call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found: %s" % method}}


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
