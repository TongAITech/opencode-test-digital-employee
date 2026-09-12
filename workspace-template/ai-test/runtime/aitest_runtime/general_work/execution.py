"""Real typed job delegation and a trusted broker for bounded worker actions.

The same R1 owns task/attempt, host-session epochs, leases and call receipts.
An external process is never launched without the separate OS-confinement port.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
from urllib.parse import quote

from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.dispatch_receipts import runtime_coordination
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, RuntimeError, SubjectRef, canonical_json, canonical_sha256
from aitest_runtime.hosted_intake import actual_host_user_turn
from aitest_runtime.r2_1.contracts import validate_secret_boundary
from aitest_runtime.r2_4.contracts import TaskReadiness
from aitest_runtime.r2_4.readiness import select_ready_tasks
from .contracts import job_subject
from .execution_contract import OWNER, POLICY, AGENTS, READ_ACTIONS, identity, require, stamp, named_write_paths
from .scheduling import SubjectReadiness
from .scoped_files import ScopedFiles, _private_write, sha
from .service import GeneralWorkService


def now(): return datetime.now(timezone.utc).isoformat()


_SCAN_CURSORS = {}  # disposable scheduling scan optimization, never job truth


class GeneralExecutionService:
    def __init__(self, runtime, workspace_root, session_provider=None):
        self.runtime = runtime
        self.workspace = Path(workspace_root).resolve(strict=True)
        self.provider = session_provider or DirectoryScopedOpenCodeSessionProvider(self.workspace)
        self.jobs = GeneralWorkService(runtime)
        self.private = runtime.db_path.parent

    def _subject(self, job_id):
        require(isinstance(job_id, str), "GENERAL_JOB_ID_REQUIRED")
        for kind, prefix in (("GENERAL_WORK", "general-work:v1:"), ("RUNTIME_DIAGNOSIS", "runtime-diagnosis:v1:")):
            if job_id.startswith(prefix): return SubjectRef(kind, job_id)
        raise RuntimeError("GENERAL_JOB_KIND_REQUIRED", "a GeneralWork or RuntimeDiagnosis job is required")

    def _job(self, subject): return self.runtime.get_subject_state(subject).root_state

    def _record(self, subject, operation, data):
        result = self.runtime.execute(CommandEnvelope("general-command-" + uuid.uuid4().hex,
            "RECORD_" + subject.subject_kind + "_EXECUTION", subject.subject_id,
            self.runtime.get_head_seq(subject.subject_id), ActorRef("SYSTEM", OWNER),
            {"subject": subject.to_dict(), "operation": operation, "data": data}))
        if not result.ok: raise result.error or RuntimeError("GENERAL_EXECUTION_RECORD_FAILED", "R1 rejected the transition")
        return self._job(subject)

    def _summary(self, subject, *, reason=None):
        job = self._job(subject); e = job.execution
        result = {"truth_source": "R1_EVENT_STREAM", "result_type": "ENGINEERING_RESULT" if subject.subject_kind == "GENERAL_WORK" else "RUNTIME_DIAGNOSIS_RESULT",
            "subject": subject.to_dict(), "job_id": job.job_id, "status": job.status,
            "summary": job.summary, "checkpoint": e.get("checkpoint"), "policy_revision": e.get("policy_revision"),
            "purpose": e.get("purpose"), "capabilities": e.get("capabilities", []), "write_roots": e.get("write_roots", []), "write_paths": e.get("write_paths", []),
            "task_id": e.get("task_id"), "root_attempt_id": e.get("root_attempt_id"), "logical_agent_id": e.get("logical_agent_id"),
            "epoch": e.get("epoch"), "session_id": e.get("sessions", {}).get(str(e.get("epoch")), {}).get("session_id"),
            "business_cursor": e.get("business_cursor", 0)}
        if reason: result["reason"] = reason
        return result

    def start(self, admitted, owner):
        # This is a trusted in-process seam; it nevertheless re-reads real Host
        # provenance. Model-supplied JSON cannot create an executable typed job.
        turn = actual_host_user_turn(self.provider)
        require(admitted.get("host_turn_ref") == turn.provenance(), "GENERAL_HOST_TURN_MISMATCH")
        require(admitted.get("intent") in {"GENERAL_WORK", "AITEST_DIAGNOSIS"} and admitted.get("status") == "DELEGATION_REQUIRED", "GENERAL_ADMISSION_REQUIRED")
        proposal = admitted["proposal"]
        operation_text = turn.text[proposal["start"]:proposal["end"]]
        require(admitted.get("operation_text") == operation_text and bool(operation_text.strip()), "GENERAL_OPERATION_TEXT_MISMATCH")
        require(admitted.get("request_digest") == canonical_sha256({"host_content": turn.source_digest, "proposal": proposal}), "GENERAL_REQUEST_DIGEST_MISMATCH")
        kind = "RUNTIME_DIAGNOSIS" if admitted["intent"] == "AITEST_DIAGNOSIS" else "GENERAL_WORK"
        subject = job_subject(kind, admitted["operation_id"])
        with runtime_coordination(self.runtime.db_path):
            receipt = owner.claim(admitted)
            if receipt["state"] == "RECONCILE_REQUIRED":
                return {"status": "RECONCILE_REQUIRED", "truth_source": "R1_EVENT_STREAM", "reason": "INTERACTION_RECEIPT_RECONCILIATION_REQUIRED"}
            if not self.runtime.get_head_seq(subject.subject_id):
                purpose = proposal.get("arguments", {}).get("purpose") or operation_text
                self.jobs.create(subject_kind=kind, operation_id=admitted["operation_id"], host_turn_ref=turn.provenance(),
                    intent=purpose, actor=ActorRef("SYSTEM", "interaction-admission"), operation_text=operation_text)
            if receipt["state"] == "CLAIMED": owner.bind(admitted["operation_id"], subject.to_dict())
            else: require(receipt["bound_subject"] == subject.to_dict(), "GENERAL_RECEIPT_TARGET_MISMATCH")
            job = self._job(subject)
            if not job.execution:
                self._prepare_created(subject)
            if job.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
                self._provision(subject)
                self._prompt(subject)
            result = self._summary(subject)
            if owner.receipt(admitted["operation_id"])["state"] == "BOUND": owner.complete(admitted["operation_id"], result)
            return result

    def _prepare_created(self, subject):
        from aitest_runtime.interaction_receipts import R1InteractionOwner
        job = self._job(subject)
        require(job.status == "CREATED" and not job.execution and bool(job.operation_text), "GENERAL_DURABLE_EXECUTION_INTENT_REQUIRED")
        owner = R1InteractionOwner(self.runtime); receipt = owner.receipt(job.operation_id)
        require(receipt is not None and receipt["host_turn_ref"] == job.host_turn_ref, "GENERAL_ADMISSION_RECEIPT_REQUIRED")
        if receipt["state"] == "CLAIMED": owner.bind(job.operation_id, subject.to_dict()); receipt = owner.receipt(job.operation_id)
        require(receipt["state"] == "BOUND" and receipt["bound_subject"] == subject.to_dict(), "GENERAL_ADMISSION_RECEIPT_REQUIRED")
        action = receipt["action"]; operation_text = job.operation_text
        capabilities = READ_ACTIONS | ({"write_file"} if action in {"write", "run", "diagnose"} else set()) | ({"terminal", "git_inspect"} if action in {"run", "diagnose"} else set())
        expiry = (stamp(receipt["host_turn_ref"]["observed_at"]) + timedelta(hours=8)).isoformat()
        require(stamp(now()) < stamp(expiry), "GENERAL_EXECUTION_LEASE_EXPIRED")
        return self._record(subject, "PREPARE", {"policy_revision": POLICY, "workspace_root": str(self.workspace),
            "workspace_digest": canonical_sha256(str(self.workspace)), "task_id": identity(job.job_id, "task"),
            "root_attempt_id": identity(job.job_id, "attempt"), "logical_agent_id": identity(job.job_id, "agent"),
            "purpose": operation_text, "operation_kind": action, "capabilities": sorted(capabilities), "read_roots": ["."],
            "write_roots": ["notes", "general-work/" + identity(job.job_id, "scratch")], "write_paths": named_write_paths(operation_text), "network_boundary": "DENY_ALL",
            "max_calls": 256, "max_process_seconds": 120, "expires_at": expiry, "source_operation": job.operation_id})

    def _provision(self, subject):
        job = self._job(subject); e = job.execution
        if e["epoch"] and e["sessions"][str(e["epoch"])]["state"] == "BOUND": return
        if not e["epoch"]:
            report = SubjectReadiness(subject, self.runtime.get_head_seq(job.job_id), (TaskReadiness(e["task_id"], "READY"),))
            selected = select_ready_tasks(report, {"policy_id": POLICY, "policy_version": 1, "max_dispatches_per_cycle": 1},
                {"budget_id": job.job_id, "max_cycles": 256, "max_dispatches": 1, "deadline": e["expires_at"], "budget_limit": 256},
                {"loop_id": job.job_id, "budget_id": job.job_id, "cycle": 0, "dispatches_used": 0, "budget_used": 0,
                 "observed_at": now(), "source_ref": "r1://" + job.job_id, "source_digest": canonical_sha256(e)})
            require(len(selected) == 1 and selected[0].task_id == e["task_id"], "GENERAL_SCHEDULER_NOT_READY")
            self._record(subject, "PROVISION_CLAIM", {"epoch": 1, "provision_id": identity(job.job_id, "session-1"),
                "agent": AGENTS[subject.subject_kind], "checkpoint_cursor": e["business_cursor"]})
        e = self._job(subject).execution; s = e["sessions"][str(e["epoch"])]
        title = "AITest General " + s["provision_id"]
        sessions = [row for row in self.provider.list_sessions() if row.title == title]
        require(len(sessions) <= 1, "GENERAL_SESSION_PROVISION_AMBIGUOUS")
        actual = sessions[0] if sessions else self.provider.create_session(title=title)
        require(Path(actual.directory).resolve() == self.workspace, "GENERAL_HOST_WORKSPACE_MISMATCH")
        self._record(subject, "SESSION_BOUND", {"epoch": e["epoch"], "provision_id": s["provision_id"], "session_id": actual.session_id, "agent": s["agent"]})

    def _prompt(self, subject, mode="INITIAL"):
        job = self._job(subject); e = job.execution; s = e["sessions"][str(e["epoch"])]
        if mode == "INITIAL":
            first = next((d for d in e["dispatches"].values() if d["mode"] == "INITIAL" and d["epoch"] == e["epoch"]), None)
            if first:
                if first["state"] != "ACCEPTED": self._reconcile_prompt(subject, first)
                return "INITIAL_ALREADY_SENT"
        did = identity(job.job_id, "prompt-" + str(e["epoch"]) + "-" + str(e["business_cursor"]) + "-" + mode)
        prior = e["dispatches"].get(did)
        if prior:
            if prior["state"] != "ACCEPTED": self._reconcile_prompt(subject, prior)
            return "DIAGNOSIS_REQUIRED_NO_PROGRESS" if mode == "AUTO_CONTINUE" else "INITIAL_ALREADY_SENT"
        body = {"schema": "aitest.general-bootstrap.v1", "runtime_dispatch_id": did, "subject": subject.to_dict(),
            "job_id": job.job_id, "first_tool_call": {"action": "status", "payload": {"job_id": job.job_id}},
            "task_id": e["task_id"], "root_attempt_id": e["root_attempt_id"], "logical_agent_id": e["logical_agent_id"],
            "epoch": e["epoch"], "purpose": e["purpose"], "capabilities": e["capabilities"], "write_roots": e["write_roots"],
            "network_boundary": "DENY_ALL", "checkpoint": e["checkpoint"], "result_type": self._summary(subject)["result_type"],
            "instruction": "Use aitest_general_worker with this job_id. Perform the authorized task and call complete with verified result references. Never ask the user to run internal commands. Terminal requires the OS isolation backend; report a technical capability failure when unavailable."}
        text = canonical_json(body)
        require(len(text.encode()) <= 16384, "GENERAL_BOOTSTRAP_BYTE_BUDGET")
        data = {"dispatch_id": did, "epoch": e["epoch"], "context_digest": sha(text.encode()), "business_cursor": e["business_cursor"], "mode": mode, "requested_at": now(), "receipt": None}
        self._record(subject, "PROMPT_CLAIM", data)
        try: self.provider.send_context(session_id=s["session_id"], agent=s["agent"], text=text)
        except Exception:
            self._record(subject, "PROMPT_UNKNOWN", data)
            raise
        self._record(subject, "PROMPT_ACCEPTED", data)
        return "PROMPT_SENT"

    def _reconcile_prompt(self, subject, record):
        e = self._job(subject).execution
        finder = getattr(self.provider, "find_context_receipt", None)
        receipt = finder(e["sessions"][str(record["epoch"])]["session_id"], record["context_digest"]) if finder else None
        require(receipt is not None, "GENERAL_PROMPT_RECONCILIATION_REQUIRED")
        self._record(subject, "PROMPT_ACCEPTED", {k: record[k] for k in ("dispatch_id", "epoch", "context_digest", "business_cursor", "mode", "requested_at")} | {"receipt": receipt})

    def _caller(self, subject, action, payload):
        job = self._job(subject); e = job.execution
        require(bool(e), "GENERAL_JOB_NOT_ACTIVE")
        require(stamp(now()) < stamp(e["expires_at"]), "GENERAL_EXECUTION_LEASE_EXPIRED")
        require(e["workspace_root"] == str(self.workspace) and e["policy_revision"] == POLICY, "GENERAL_EXECUTION_POLICY_MISMATCH")
        sid, mid, call_id = (os.environ.get(k, "") for k in ("AITEST_HOST_SESSION_ID", "AITEST_HOST_MESSAGE_ID", "AITEST_HOST_CALL_ID"))
        binding = e["sessions"].get(str(e["epoch"]), {})
        require(binding.get("state") == "BOUND" and sid == binding["session_id"] and bool(mid), "STALE_CALLER")
        row = self.provider._request("GET", "/session/" + quote(sid, safe="") + "/message/" + quote(mid, safe="") + "?" + self.provider._directory_query())
        require(isinstance(row, dict) and len(canonical_json(row).encode()) <= 262144, "GENERAL_HOST_MESSAGE_INVALID_OR_OVER_BUDGET")
        info = row.get("info", {})
        require(info.get("sessionID") == sid and info.get("id") == mid and info.get("role") == "assistant" and info.get("agent") == binding["agent"], "GENERAL_HOST_AGENT_MISMATCH")
        raw_input = {"action": action, "payload": payload}
        parts = [p for p in row.get("parts", []) if isinstance(p, dict) and p.get("type") == "tool" and p.get("tool") == "aitest_general_worker"
            and p.get("sessionID") == sid and p.get("messageID") == mid and p.get("state", {}).get("status") == "running"
            and p.get("state", {}).get("input") == raw_input and (not call_id or p.get("callID") == call_id)]
        require(len(parts) == 1 and isinstance(parts[0].get("callID"), str) and bool(parts[0]["callID"]), "GENERAL_ACTUAL_TOOL_CALL_REQUIRED")
        spec = {k: v for k, v in payload.items() if k not in {"job_id", "content"}}
        if "content" in payload: spec["content_sha256"] = sha(payload["content"].encode())
        return {"session_id": sid, "message_id": mid, "call_id": parts[0]["callID"], "input_digest": canonical_sha256(raw_input),
                "spec_digest": canonical_sha256({"action": action, "request_spec": spec}), "observed_at": now()}

    def _payload(self, action, p):
        fields = {"status": (set(), set()), "read_file": ({"path"}, {"offset", "limit"}),
            "search_files": ({"path", "pattern"}, {"glob", "offset", "limit"}), "write_file": ({"path", "expected_sha256", "content"}, set()),
            "git_inspect": ({"path", "operation"}, {"rev"}), "terminal": ({"argv", "cwd"}, {"timeout_seconds"}),
            "checkpoint": ({"summary"}, {"artifact_refs"}), "complete": ({"summary"}, {"result_refs"})}
        require(action in fields and isinstance(p, dict), "GENERAL_ACTION_INVALID")
        needed, optional = fields[action]
        require(needed | {"job_id"} <= set(p) and not set(p) - needed - optional - {"job_id"}, "GENERAL_ACTION_PAYLOAD_INVALID")
        require(len(canonical_json(p).encode()) <= 131072, "GENERAL_TOOL_INPUT_BYTE_BUDGET")
        validate_secret_boundary(p)

    def _cache(self, call_key): return self.private / "general-results" / (call_key + ".json")

    def _write_receipt(self, subject, call, result, status="COMPLETED"):
        result = {**result, "truth_source": "R1_EVENT_STREAM", "result_type": self._summary(subject)["result_type"],
                  "job_id": subject.subject_id, "status": status}
        require(len(canonical_json(result).encode()) <= 32768, "GENERAL_TOOL_OUTPUT_BYTE_BUDGET")
        validate_secret_boundary(result)
        cache = self._cache(call["call_key"]); cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = canonical_json(result).encode()
        if cache.exists():
            require(cache.read_bytes() == data, "GENERAL_RECEIPT_CACHE_CONFLICT")
        else: _private_write(cache, data)
        self._record(subject, "CALL_RECEIPT", {"call_key": call["call_key"], "request_digest": call["request_digest"],
            "receipt": {"artifact_ref": "general-results/" + cache.name, "sha256": sha(data), "status": status,
                "observed_refs": [{"path": result["path"], "sha256": result["sha256"]}] if "path" in result and "sha256" in result else []}})
        return result

    def _read_receipt(self, call):
        raw = self._cache(call["call_key"]).read_bytes()
        require(sha(raw) == call["receipt"]["sha256"], "GENERAL_RECEIPT_CACHE_CORRUPTED")
        return json.loads(raw)

    def worker_command(self, action, payload):
        self._payload(action, payload)
        subject = self._subject(payload["job_id"])
        with runtime_coordination(self.runtime.db_path):
            host = self._caller(subject, action, payload)
            e = self._job(subject).execution
            require(action in e["capabilities"], "GENERAL_EXECUTION_CAPABILITY_DENIED")
            call_key = identity(subject.subject_id, "call-" + canonical_sha256({k: host[k] for k in ("session_id", "message_id", "call_id")}))
            request_digest = canonical_sha256({"action": action, "payload": payload})
            existing = e["calls"].get(call_key)
            if existing:
                require(existing["request_digest"] == request_digest, "GENERAL_CALL_REPLAY_CONFLICT")
                if existing["state"] == "RECEIPTED":
                    result = self._read_receipt(existing)
                    self._finish_receipted_call(subject, existing, result)
                    return result
                result = self._reconcile_call(subject, existing)
                self._finish_receipted_call(subject, self._job(subject).execution["calls"][call_key], result)
                return result
            spec = {k: v for k, v in payload.items() if k not in {"job_id", "content"}}
            if "content" in payload: spec["content_sha256"] = sha(payload["content"].encode())
            call = {"call_key": call_key, "epoch": e["epoch"], "host_call": host, "action": action,
                    "request_digest": request_digest, "request_spec": spec}
            self._record(subject, "CALL_CLAIM", call)
            broker = ScopedFiles(self.workspace, e["write_roots"], self.private, e["write_paths"])
            try:
                if action == "status": result = self._summary(subject)
                elif action == "read_file": result = broker.read(payload["path"], payload.get("offset", 0), payload.get("limit", 8192))
                elif action == "search_files": result = broker.search(payload["path"], payload["pattern"], payload.get("glob", "*"), payload.get("offset", 0), payload.get("limit", 20))
                elif action == "write_file": result = broker.write(payload["path"], payload["expected_sha256"], payload["content"], call_key)
                elif action in {"terminal", "git_inspect"}:
                    # No process fallback. The qualified OS executor is integrated
                    # separately; a tool-name allowlist is not a confinement proof.
                    raise RuntimeError("GENERAL_OS_CONFINEMENT_UNAVAILABLE", "OS-confined process execution is not installed")
                else:
                    result = self._validated_result(subject, action, payload, broker)
            except Exception as exc:
                if action == "write_file" and (not isinstance(exc, RuntimeError) or exc.code == "GENERAL_WRITE_RECONCILIATION_REQUIRED"):
                    # An OS exception can follow installation (e.g. fsync failed).
                    # Keep the intent unresolved until postimage readback.
                    raise RuntimeError("GENERAL_EFFECT_RECONCILIATION_REQUIRED", "file effect requires readback") from exc
                # Only known completed broker errors become FAILED. An abrupt
                # process death leaves CLAIMED; the supervisor reconciles it.
                result = self._write_receipt(subject, call, {"reason": getattr(exc, "code", type(exc).__name__)}, "FAILED")
                return result
            result = self._write_receipt(subject, call, result)
            if action in {"checkpoint", "complete"}:
                self._record(subject, action.upper(), {"call_key": call_key, "summary": payload["summary"], "result_refs": result["result_refs"]})
            return result

    def _validated_result(self, subject, action, payload, broker):
        refs = payload.get("result_refs" if action == "complete" else "artifact_refs", [])
        require(isinstance(refs, list) and len(refs) <= 16, "GENERAL_RESULT_REFERENCE_BUDGET")
        for ref in refs:
            require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "GENERAL_RESULT_REFERENCE_INVALID")
            observed = broker.read(ref["path"], 0, 1)
            require(observed["sha256"] == ref["sha256"], "GENERAL_RESULT_REFERENCE_CHANGED")
        require(isinstance(payload["summary"], str) and 0 < len(payload["summary"].encode()) <= 4096, "GENERAL_RESULT_SUMMARY_INVALID")
        if action == "complete":
            from .execution_contract import validate_completion
            validate_completion(self._job(subject).execution, refs)
        return {"summary": payload["summary"], "result_refs": refs}

    def _reconcile_call(self, subject, call):
        cache = self._cache(call["call_key"])
        if cache.exists():
            data = json.loads(cache.read_bytes())
            status = data.get("status")
            require(status in {"COMPLETED", "FAILED", "RECONCILED"}, "GENERAL_RECEIPT_CACHE_INVALID")
            return self._write_receipt(subject, call, data, status)
        e = self._job(subject).execution; spec = call["request_spec"]
        require(stamp(now()) < stamp(e["expires_at"]), "GENERAL_EXECUTION_LEASE_EXPIRED")
        broker = ScopedFiles(self.workspace, e["write_roots"], self.private, e["write_paths"])
        if call["action"] in {"read_file", "search_files", "status"}:
            try:
                if call["action"] == "read_file": result = broker.read(spec["path"], spec.get("offset", 0), spec.get("limit", 8192))
                elif call["action"] == "search_files": result = broker.search(spec["path"], spec["pattern"], spec.get("glob", "*"), spec.get("offset", 0), spec.get("limit", 20))
                else: result = self._summary(subject)
                return self._write_receipt(subject, call, {**result, "reconciliation": "FRESH_READ_ONLY_OBSERVATION"}, "RECONCILED")
            except (OSError, RuntimeError) as exc:
                return self._write_receipt(subject, call, {"reason": getattr(exc, "code", type(exc).__name__)}, "FAILED")
        if call["action"] in {"complete", "checkpoint"}:
            try:
                result = self._validated_result(subject, call["action"], spec, broker)
            except (OSError, RuntimeError) as exc:
                return self._write_receipt(subject, call, {"reason": getattr(exc, "code", type(exc).__name__)}, "FAILED")
            return self._write_receipt(subject, call, {**result, "reconciliation": "FRESH_REFERENCE_AND_EFFECT_VERIFICATION"})
        if call["action"] == "write_file":
            e = self._job(subject).execution; spec = call["request_spec"]
            broker = ScopedFiles(self.workspace, e["write_roots"], self.private, e["write_paths"])
            backup = self.private / "general-backups" / call["call_key"]
            transaction = backup / "transaction.json"
            if transaction.is_file():
                meta = json.loads(transaction.read_text())
                unresolved = self.workspace / Path(spec["path"]).parent / meta["temporary_name"]
                require(not any(Path(str(unresolved) + suffix).exists() for suffix in ("", ".displaced", ".second")), "GENERAL_WRITE_RECONCILIATION_REQUIRED")
            current = broker.read(spec["path"], 0, 1)
            if current["sha256"] == spec["content_sha256"] and (backup / "change.diff").is_file():
                return self._write_receipt(subject, call, {"path": current["path"], "sha256": current["sha256"],
                    "bytes": current["bytes"], "before_sha256": spec["expected_sha256"], "backup_ref": "general-backups/" + call["call_key"],
                    "reconciliation": "STATE_EQUIVALENCE_READBACK", "physical_write_count": "NOT_INFERRED_FROM_READBACK"}, "RECONCILED")
        # A possible process/file effect is never blindly executed again.
        raise RuntimeError("GENERAL_EFFECT_RECONCILIATION_REQUIRED", "an unfinished call requires effect-specific readback")

    def _finish_receipted_call(self, subject, call, result=None):
        if call["action"] not in {"checkpoint", "complete"} or call["receipt"]["status"] != "COMPLETED": return
        job = self._job(subject)
        if job.status != "ACTIVE" or (job.execution.get("checkpoint") or {}).get("call_key") == call["call_key"]: return
        result = result or self._read_receipt(call)
        self._record(subject, call["action"].upper(), {"call_key": call["call_key"], "summary": result["summary"], "result_refs": result["result_refs"]})

    def _recover_claimed_jobs(self):
        # Projection is only a bounded candidate index. Replay each receipt before
        # restoring the exact accepted intent; never recover from conversation.
        from aitest_runtime.durable_core.schema import connect
        from aitest_runtime.interaction_receipts import ROOT_KIND
        conn = connect(self.runtime.db_path)
        try:
            scan = str(self.runtime.db_path.resolve()) + ":claims"
            cursor = _SCAN_CURSORS.get(scan, "")
            query = "SELECT subject_id FROM interaction_operation_projection WHERE json_extract(state_json,'$.receipt.state')='CLAIMED' AND json_extract(state_json,'$.receipt.operation_text') IS NOT NULL AND subject_id>? ORDER BY subject_id LIMIT 128"
            rows = conn.execute(query, (cursor,)).fetchall()
            if not rows and cursor: rows = conn.execute(query, ("",)).fetchall()
            if len(_SCAN_CURSORS) >= 64: _SCAN_CURSORS.clear()
            _SCAN_CURSORS[scan] = rows[-1]["subject_id"] if rows else ""
        finally: conn.close()
        errors = []
        for row in rows:
            with runtime_coordination(self.runtime.db_path):
                receipt = self.runtime.get_subject_state(SubjectRef(ROOT_KIND, row["subject_id"])).root_state.receipt
                if receipt["state"] != "CLAIMED" or receipt["intent"] not in {"GENERAL_WORK", "AITEST_DIAGNOSIS"} or not receipt.get("operation_text"): continue
                kind = "GENERAL_WORK" if receipt["intent"] == "GENERAL_WORK" else "RUNTIME_DIAGNOSIS"
                subject = job_subject(kind, receipt["operation_id"])
                if self.runtime.get_head_seq(subject.subject_id): continue
                try:
                    require(stamp(now()) < stamp(receipt["host_turn_ref"]["observed_at"]) + timedelta(hours=8), "GENERAL_EXECUTION_LEASE_EXPIRED")
                    purpose = receipt["proposal"].get("arguments", {}).get("purpose") or receipt["operation_text"]
                    self.jobs.create(subject_kind=kind, operation_id=receipt["operation_id"], host_turn_ref=receipt["host_turn_ref"],
                        intent=purpose, actor=ActorRef("SYSTEM", "interaction-admission"), operation_text=receipt["operation_text"])
                except Exception as exc:
                    errors.append({"operation_id": receipt["operation_id"], "reason": getattr(exc, "code", type(exc).__name__)})
        return errors

    def supervise_once(self):
        recovery_errors = self._recover_claimed_jobs()
        from aitest_runtime.durable_core.schema import connect
        conn = connect(self.runtime.db_path)
        try:
            scan = str(self.runtime.db_path.resolve()); cursor = _SCAN_CURSORS.get(scan, "")
            query = "SELECT job_id AS mission_id FROM general_work_projection WHERE json_extract(state_json,'$.status') IN ('CREATED','ACTIVE') AND job_id>? ORDER BY job_id LIMIT 128"
            rows = conn.execute(query, (cursor,)).fetchall()
            if not rows and cursor: rows = conn.execute(query, ("",)).fetchall()
            if len(_SCAN_CURSORS) >= 64: _SCAN_CURSORS.clear()
            _SCAN_CURSORS[scan] = rows[-1]["mission_id"] if rows else ""
        finally: conn.close()
        results = []
        for row in rows:
            subject = self._subject(row["mission_id"])
            with runtime_coordination(self.runtime.db_path):
                job = self._job(subject)
                if job.status == "CREATED" and job.operation_text:
                    try: self._prepare_created(subject); job = self._job(subject)
                    except Exception as exc:
                        results.append(self._summary(subject, reason=getattr(exc, "code", type(exc).__name__))); continue
                if job.status != "ACTIVE" or not job.execution: continue
                try:
                    for call in job.execution["calls"].values():
                        if call["state"] == "CLAIMED": self._reconcile_call(subject, call)
                        current = self._job(subject).execution["calls"][call["call_key"]]
                        self._finish_receipted_call(subject, current)
                    if self._job(subject).status != "ACTIVE":
                        results.append(self._summary(subject)); continue
                    self._provision(subject)
                    e = self._job(subject).execution
                    for dispatch in e["dispatches"].values():
                        if dispatch["state"] != "ACCEPTED": self._reconcile_prompt(subject, dispatch)
                    sid = e["sessions"][str(e["epoch"])]["session_id"]
                    activity = self.provider.session_activity(sid)
                    if activity == "idle":
                        initial = next((d for d in e["dispatches"].values() if d["mode"] == "INITIAL" and d["epoch"] == e["epoch"]), None)
                        if initial is None: reason = self._prompt(subject)
                        elif (stamp(now()) - stamp(initial["requested_at"])).total_seconds() < 2: reason = "INITIAL_DISPATCH_GRACE"
                        else: reason = self._prompt(subject, "AUTO_CONTINUE")
                        results.append(self._summary(subject, reason=reason))
                    else: results.append(self._summary(subject, reason="BUSY_EXTERNAL_WORK" if activity == "busy" else "WAITING_QUOTA"))
                    from aitest_runtime.interaction_receipts import R1InteractionOwner
                    owner = R1InteractionOwner(self.runtime)
                    if owner.receipt(job.operation_id)["state"] == "BOUND": owner.complete(job.operation_id, self._summary(subject))
                except Exception as exc:
                    results.append(self._summary(subject, reason=getattr(exc, "code", type(exc).__name__)))
        return {"truth_source": "R1_EVENT_STREAM", "jobs": results, "admission_recovery_errors": recovery_errors}

    def status(self, host_session_id):
        """Bounded read-only results for the admitting Primary conversation."""
        from aitest_runtime.durable_core.schema import connect
        require(isinstance(host_session_id, str) and bool(host_session_id), "HOST_USER_TURN_REQUIRED")
        conn = connect(self.runtime.db_path)
        try:
            rows = conn.execute("SELECT job_id AS mission_id FROM general_work_projection WHERE json_extract(state_json,'$.host_turn_ref.host_session_id')=? ORDER BY json_extract(state_json,'$.created_at') DESC,job_id LIMIT 17", (host_session_id,)).fetchall()
        finally: conn.close()
        jobs = []
        for row in rows:
            subject = self._subject(row["mission_id"]); job = self._job(subject)
            if job.host_turn_ref.get("host_session_id") == host_session_id: jobs.append(self._summary(subject))
        return {"truth_source": "R1_EVENT_STREAM", "jobs": jobs[:16], "older_results_truncated": len(jobs) > 16}
