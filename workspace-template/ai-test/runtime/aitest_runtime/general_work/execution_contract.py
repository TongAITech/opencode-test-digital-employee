"""CC-01 root-owned execution subrecords; no core Mission/Session identities.

Every transition is checked on live command admission and canonical replay.
Only the trusted execution owner may append; model payloads never contain a lease.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import re
from typing import Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_json, canonical_sha256
from aitest_runtime.r2_1.contracts import validate_secret_boundary

OWNER = "general-execution"
POLICY = "general-execution.v4.1"
AGENTS = {"GENERAL_WORK": "aitest-general-worker", "RUNTIME_DIAGNOSIS": "aitest-runtime-diagnosis"}
READ_ACTIONS = frozenset({"status", "read_file", "search_files", "checkpoint", "complete"})
ALL_ACTIONS = READ_ACTIONS | {"write_file", "git_inspect", "terminal"}


def named_write_paths(purpose):
    # Exact file names in the verified human clause may extend the preauthorized
    # workspace file scope, never protected runtime/configuration objects.
    pattern = r"(?:^|[\s\"'“‘`])([A-Za-z0-9_.\-/]+\.[A-Za-z0-9]{1,12})(?=$|[\s\"'”’`，。；,;])"
    return sorted(set(re.findall(pattern, purpose)))[:16]


def require(condition, code):
    if not condition:
        raise RuntimeError(code, code)


def require_owner(actor_type, actor_id, session_id):
    require((actor_type, actor_id, session_id) == ("SYSTEM", OWNER, None), "GENERAL_EXECUTION_OWNER_REQUIRED")


def identity(job_id, kind):
    return "general-" + kind + "-" + canonical_sha256({"job_id": job_id, "kind": kind})


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def bounded(value, limit=1024):
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= limit


def exact(value, fields):
    require(isinstance(value, Mapping) and set(value) == set(fields.split()), "GENERAL_EXECUTION_SCHEMA_INVALID")


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "GENERAL_EXECUTION_TIME_INVALID")
        return result
    except (AttributeError, ValueError):
        raise RuntimeError("GENERAL_EXECUTION_TIME_INVALID", "invalid timestamp") from None


def validate_completion(execution, refs):
    kind = execution["operation_kind"]
    eligible = {"write_file"} if kind == "write" else {"terminal"} if kind == "run" else {"read_file", "search_files", "write_file", "terminal", "git_inspect"}
    observed = [c for c in execution["calls"].values() if c["action"] in eligible and c["state"] == "RECEIPTED" and c["receipt"]["status"] in {"COMPLETED", "RECONCILED"}]
    require(bool(observed), "GENERAL_COMPLETION_EFFECT_REQUIRED")
    if kind == "write":
        produced = [ref for call in observed for ref in call["receipt"]["observed_refs"]]
        require(bool(refs) and all(ref in produced for ref in refs), "GENERAL_COMPLETION_PRODUCED_REFERENCE_REQUIRED")


def execution_transition(state, payload):
    exact(payload, "subject operation data")
    require(payload["subject"] == {"subject_kind": state.subject_kind, "subject_id": state.job_id}, "GENERAL_EXECUTION_ROOT_MISMATCH")
    require(len(canonical_json(payload).encode()) <= 32768, "GENERAL_EXECUTION_EVENT_BUDGET")
    validate_secret_boundary(payload)
    op, data = payload["operation"], payload["data"]
    e = deepcopy(dict(state.execution))
    require(state.status not in {None, "COMPLETED", "FAILED", "CANCELLED"} or op in {"CALL_RECEIPT", "PROMPT_ACCEPTED", "PROMPT_UNKNOWN"}, "GENERAL_JOB_NOT_EXECUTABLE")
    if op == "PREPARE":
        require(not e and state.status == "CREATED", "GENERAL_EXECUTION_ALREADY_PREPARED")
        exact(data, "policy_revision workspace_root workspace_digest task_id root_attempt_id logical_agent_id purpose operation_kind capabilities read_roots write_roots write_paths network_boundary max_calls max_process_seconds expires_at source_operation")
        require(data["policy_revision"] == POLICY and data["source_operation"] == state.operation_id, "GENERAL_EXECUTION_POLICY_MISMATCH")
        for field, kind in (("task_id", "task"), ("root_attempt_id", "attempt"), ("logical_agent_id", "agent")):
            require(data[field] == identity(state.job_id, kind), "GENERAL_EXECUTION_LINEAGE_MISMATCH")
        require(bounded(data["purpose"], 8192) and bounded(data["workspace_root"], 4096) and digest(data["workspace_digest"]), "GENERAL_EXECUTION_SCOPE_INVALID")
        require(data["operation_kind"] in {"read", "write", "run", "diagnose"}, "GENERAL_EXECUTION_KIND_INVALID")
        allowed = READ_ACTIONS | ({"write_file"} if data["operation_kind"] in {"write", "run", "diagnose"} else set()) | ({"terminal", "git_inspect"} if data["operation_kind"] in {"run", "diagnose"} else set())
        require(set(data["capabilities"]) == allowed and len(data["capabilities"]) == len(allowed), "GENERAL_EXECUTION_CAPABILITY_INVALID")
        require(data["read_roots"] == ["."] and data["write_roots"] == ["notes", "general-work/" + identity(state.job_id, "scratch")], "GENERAL_EXECUTION_SCOPE_INVALID")
        require(data["write_paths"] == named_write_paths(data["purpose"]), "GENERAL_EXECUTION_SCOPE_INVALID")
        require(data["network_boundary"] == "DENY_ALL" and data["max_calls"] == 256 and data["max_process_seconds"] == 120, "GENERAL_EXECUTION_BUDGET_INVALID")
        stamp(data["expires_at"])
        e = {**dict(data), "epoch": 0, "sessions": {}, "dispatches": {}, "calls": {}, "checkpoint": None, "business_cursor": 0}
        return replace(state, status="ACTIVE", execution=e)
    require(bool(e), "GENERAL_EXECUTION_NOT_PREPARED")
    if op == "PROVISION_CLAIM":
        exact(data, "epoch provision_id agent checkpoint_cursor")
        epoch = data["epoch"]
        require(type(epoch) is int and epoch == e["epoch"] + 1 and epoch <= 8, "GENERAL_EXECUTION_EPOCH_INVALID")
        require(data["provision_id"] == identity(state.job_id, "session-" + str(epoch)) and data["agent"] == AGENTS[state.subject_kind], "GENERAL_EXECUTION_SESSION_IDENTITY_INVALID")
        require(data["checkpoint_cursor"] == e["business_cursor"], "GENERAL_EXECUTION_CHECKPOINT_MISMATCH")
        require(not any(c["state"] == "CLAIMED" for c in e["calls"].values()), "GENERAL_EFFECT_RECONCILIATION_REQUIRED")
        require(not any(d["state"] != "ACCEPTED" for d in e["dispatches"].values()), "GENERAL_PROMPT_RECONCILIATION_REQUIRED")
        require(state.status == "ACTIVE", "GENERAL_JOB_NOT_ACTIVE")
        e["epoch"] = epoch
        e["sessions"][str(epoch)] = {**dict(data), "state": "CLAIMED", "session_id": None}
    elif op == "SESSION_BOUND":
        exact(data, "epoch provision_id session_id agent")
        require(data["epoch"] == e["epoch"], "GENERAL_EXECUTION_STALE_EPOCH")
        s = e["sessions"][str(e["epoch"])]
        require(s["state"] == "CLAIMED" and s["provision_id"] == data["provision_id"] and s["agent"] == data["agent"], "GENERAL_EXECUTION_SESSION_BINDING_INVALID")
        require(bounded(data["session_id"], 256) and all(s0["session_id"] != data["session_id"] for s0 in e["sessions"].values()), "GENERAL_EXECUTION_SESSION_REUSED")
        s.update(state="BOUND", session_id=data["session_id"])
    elif op.startswith("PROMPT_"):
        exact(data, "dispatch_id epoch context_digest business_cursor mode requested_at receipt")
        require(data["epoch"] == e["epoch"] and e["sessions"][str(e["epoch"])]["state"] == "BOUND", "GENERAL_EXECUTION_SESSION_REQUIRED")
        require(digest(data["context_digest"]) and type(data["business_cursor"]) is int and 0 <= data["business_cursor"] <= e["business_cursor"], "GENERAL_EXECUTION_PROMPT_IDENTITY_INVALID")
        require(data["mode"] in {"INITIAL", "AUTO_CONTINUE"}, "GENERAL_EXECUTION_PROMPT_MODE_INVALID")
        stamp(data["requested_at"])
        did = identity(state.job_id, "prompt-" + str(data["epoch"]) + "-" + str(data["business_cursor"]) + "-" + data["mode"])
        require(did == data["dispatch_id"], "GENERAL_EXECUTION_PROMPT_IDENTITY_INVALID")
        prior = e["dispatches"].get(did)
        if op == "PROMPT_CLAIM":
            require(prior is None and data["receipt"] is None and state.status == "ACTIVE" and data["business_cursor"] == e["business_cursor"], "GENERAL_EXECUTION_PROMPT_ALREADY_CLAIMED")
            e["dispatches"][did] = {**dict(data), "state": "CLAIMED"}
        else:
            require(op in {"PROMPT_ACCEPTED", "PROMPT_UNKNOWN"} and prior and prior["state"] in {"CLAIMED", "UNKNOWN"}, "GENERAL_EXECUTION_PROMPT_TRANSITION_INVALID")
            require(prior["state"] != "UNKNOWN" or op == "PROMPT_ACCEPTED", "GENERAL_EXECUTION_PROMPT_TRANSITION_INVALID")
            require(all(prior[k] == data[k] for k in ("dispatch_id", "epoch", "context_digest", "business_cursor", "mode", "requested_at")), "GENERAL_EXECUTION_PROMPT_CONFLICT")
            if prior["state"] == "UNKNOWN" or data["receipt"] is not None:
                ref = data["receipt"]
                require(isinstance(ref, Mapping) and ref.get("source") == "OPENCODE_SESSION_MESSAGE_READBACK" and ref.get("session_id") == e["sessions"][str(e["epoch"])]["session_id"] and ref.get("context_digest") == data["context_digest"] and bounded(ref.get("message_id"), 256), "GENERAL_EXECUTION_PROMPT_RECEIPT_INVALID")
            prior.update(state="ACCEPTED" if op == "PROMPT_ACCEPTED" else "UNKNOWN", receipt=data["receipt"])
    elif op == "CALL_CLAIM":
        exact(data, "call_key epoch host_call action request_digest request_spec")
        require(state.status == "ACTIVE" and data["epoch"] == e["epoch"], "GENERAL_EXECUTION_STALE_OR_PAUSED")
        s = e["sessions"][str(e["epoch"])]
        require(s["state"] == "BOUND", "GENERAL_EXECUTION_SESSION_REQUIRED")
        h = data["host_call"]
        exact(h, "session_id message_id call_id input_digest spec_digest observed_at")
        require(h["session_id"] == s["session_id"] and bounded(h["message_id"], 256) and bounded(h["call_id"], 256) and digest(h["input_digest"]), "GENERAL_EXECUTION_CALLER_MISMATCH")
        require(stamp(h["observed_at"]) < stamp(e["expires_at"]), "GENERAL_EXECUTION_LEASE_EXPIRED")
        require(data["call_key"] == identity(state.job_id, "call-" + canonical_sha256({k: h[k] for k in ("session_id", "message_id", "call_id")})), "GENERAL_EXECUTION_CALL_IDENTITY_INVALID")
        require(data["action"] in e["capabilities"] and digest(data["request_digest"]), "GENERAL_EXECUTION_CAPABILITY_DENIED")
        require(data["request_digest"] == h["input_digest"] and h["spec_digest"] == canonical_sha256({"action": data["action"], "request_spec": data["request_spec"]}), "GENERAL_EXECUTION_CALL_DIGEST_MISMATCH")
        require(data["call_key"] not in e["calls"] and len(e["calls"]) < e["max_calls"], "GENERAL_EXECUTION_CALL_ALREADY_CLAIMED_OR_EXHAUSTED")
        require(not any(c["state"] == "CLAIMED" for c in e["calls"].values()), "GENERAL_EFFECT_RECONCILIATION_REQUIRED")
        e["calls"][data["call_key"]] = {**dict(data), "state": "CLAIMED", "receipt": None}
    elif op == "CALL_RECEIPT":
        exact(data, "call_key request_digest receipt")
        c = e["calls"].get(data["call_key"])
        require(c is not None and c["state"] == "CLAIMED" and c["request_digest"] == data["request_digest"], "GENERAL_EXECUTION_CALL_RECEIPT_CONFLICT")
        r = data["receipt"]
        exact(r, "artifact_ref sha256 status observed_refs")
        require(r["artifact_ref"] == "general-results/" + data["call_key"] + ".json" and digest(r["sha256"]) and r["status"] in {"COMPLETED", "FAILED", "RECONCILED"}, "GENERAL_EXECUTION_RECEIPT_INVALID")
        require(isinstance(r["observed_refs"], list) and len(r["observed_refs"]) <= 16, "GENERAL_EXECUTION_RECEIPT_INVALID")
        for ref in r["observed_refs"]:
            exact(ref, "path sha256")
            require(bounded(ref["path"]) and digest(ref["sha256"]), "GENERAL_EXECUTION_RECEIPT_INVALID")
        c.update(state="RECEIPTED", receipt=dict(r))
        if c["action"] != "status": e["business_cursor"] += 1
    elif op in {"CHECKPOINT", "COMPLETE"}:
        exact(data, "call_key summary result_refs")
        c = e["calls"].get(data["call_key"])
        require(c and c["state"] == "RECEIPTED" and c["action"] == op.lower() and c["receipt"]["status"] == "COMPLETED", "GENERAL_EXECUTION_COMPLETION_RECEIPT_REQUIRED")
        require(bounded(data["summary"], 4096) and isinstance(data["result_refs"], list) and len(data["result_refs"]) <= 16, "GENERAL_EXECUTION_RESULT_BUDGET")
        for ref in data["result_refs"]:
            exact(ref, "path sha256")
            require(bounded(ref["path"]) and digest(ref["sha256"]), "GENERAL_EXECUTION_RESULT_REFERENCE_INVALID")
        e["checkpoint"] = {**dict(data), "cursor": e["business_cursor"]}
        if op == "COMPLETE":
            validate_completion(e, data["result_refs"])
            return replace(state, status="COMPLETED", summary=data["summary"], execution=e)
    else:
        raise RuntimeError("GENERAL_EXECUTION_OPERATION_UNSUPPORTED", "unsupported execution transition")
    return replace(state, execution=e)
