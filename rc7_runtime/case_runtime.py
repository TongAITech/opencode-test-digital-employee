"""Runtime-owned RC7 case preparation and Human Gate closure.

The Agent may request preparation but cannot manufacture preparation evidence.
RC7 itself launches configured field providers, hashes request/response payloads,
persists immutable payload files, and records durable R1 Evidence. DB_CREATE is
always Human-Gated. Missing bank-only providers return FIELD_REQUIRED and are
never promoted to PASS by public engineering CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import shlex
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.preparation import (
    PreparationContractError,
    PreparationRuntime,
    PreparationSpecParser,
)
from rc6_runtime.truth import TruthRuntime

from .models import Evidence
from .node_tool_conformance import validate_call_context
from .truth_overlay import append_entity


PROVIDER_CONFIG_ENV = "PFC_RC7_CASE_PROVIDER_CONFIG"
PROVIDER_CALL_KIND = "CASE_PROVIDER_CALL"
PREPARED_ATTEMPT_KIND = "CASE_PREPARED_ATTEMPT"
HUMAN_GATE_REQUEST_KIND = "CASE_HUMAN_GATE_REQUEST"
HUMAN_GATE_APPROVAL_KIND = "CASE_HUMAN_GATE_APPROVAL"
SCHEMA_VERSION = "pfc.aitest.rc7.case-runtime.v1"


class CaseRuntimeError(RuntimeError):
    pass


class CaseRuntimeFieldRequired(CaseRuntimeError):
    def __init__(self, capability: str) -> None:
        super().__init__("FIELD_PROVIDER_REQUIRED:%s" % capability)
        self.capability = capability


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_token(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))
    return text[:120] or "unknown"


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def _mission_release(truth: TruthRuntime, mission_id: str) -> str:
    rows = truth.query("rc7_mission", mission_id=mission_id)
    if len(rows) != 1:
        raise CaseRuntimeError("CASE_RUNTIME_MISSION_NOT_UNIQUE")
    release_id = str(rows[0].get("release_id") or "").strip()
    if not release_id:
        raise CaseRuntimeError("CASE_RUNTIME_RELEASE_ID_MISSING")
    return release_id


def _write_immutable_json(state_root: Path, relative: Path, payload: object) -> Tuple[Path, str]:
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    target = state_root / "case-runtime" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = target.read_bytes()
        if hashlib.sha256(existing).hexdigest() != digest:
            raise CaseRuntimeError("CASE_RUNTIME_IMMUTABLE_PAYLOAD_CONFLICT:%s" % target)
        return target, digest
    target.write_bytes(body)
    return target, digest


def _state_ref(state_root: Path, target: Path) -> str:
    return "state://" + target.relative_to(state_root).as_posix()


class ProviderRegistry:
    """Field-provider commands are deployment configuration, never Agent text."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        configured = config_path or (Path(os.environ[PROVIDER_CONFIG_ENV]).expanduser() if os.environ.get(PROVIDER_CONFIG_ENV) else None)
        self.config_path = configured.resolve() if configured else None
        self.providers: Dict[str, Dict[str, Any]] = {}
        if self.config_path is not None:
            if not self.config_path.is_file():
                raise CaseRuntimeError("CASE_PROVIDER_CONFIG_NOT_FOUND:%s" % self.config_path)
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            providers = data.get("providers") if isinstance(data, dict) else None
            if not isinstance(providers, dict):
                raise CaseRuntimeError("CASE_PROVIDER_CONFIG_INVALID")
            for capability, raw in providers.items():
                if not isinstance(raw, dict):
                    raise CaseRuntimeError("CASE_PROVIDER_ENTRY_INVALID:%s" % capability)
                command = raw.get("command")
                if isinstance(command, str):
                    command = shlex.split(command, posix=os.name != "nt")
                if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
                    raise CaseRuntimeError("CASE_PROVIDER_COMMAND_INVALID:%s" % capability)
                self.providers[str(capability).upper()] = {
                    "provider_id": str(raw.get("provider_id") or capability).strip(),
                    "command": list(command),
                    "timeout_seconds": int(raw.get("timeout_seconds", 120)),
                    "environment": dict(raw.get("environment") or {}),
                }

    def get(self, capability: str) -> Dict[str, Any]:
        key = str(capability).upper()
        provider = self.providers.get(key)
        if provider is None:
            raise CaseRuntimeFieldRequired(key)
        return provider

    def summary(self) -> Dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "config_path": str(self.config_path) if self.config_path else None,
            "capabilities": sorted(self.providers),
        }


class ProviderExecutor:
    def __init__(self, truth: TruthRuntime, state_root: Path, registry: ProviderRegistry, *, mission_id: str, task_id: str, worker_id: str, attempt_id: str) -> None:
        self.truth = truth
        self.state_root = state_root.resolve()
        self.registry = registry
        self.mission_id = mission_id
        self.task_id = task_id
        self.worker_id = worker_id
        self.attempt_id = attempt_id
        self.release_id = _mission_release(truth, mission_id)

    def _call_id(self, capability: str, request: object) -> str:
        return "PCALL-" + hashlib.sha256(_canonical({
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "capability": capability,
            "request": request,
        })).hexdigest()[:24]

    def _existing(self, call_id: str) -> Optional[Dict[str, Any]]:
        rows = [
            row for row in self.truth.query("rc7_evidence", mission_id=self.mission_id)
            if row.get("kind") == PROVIDER_CALL_KIND and call_id in list(row.get("subject_refs") or [])
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise CaseRuntimeError("CASE_PROVIDER_CALL_EVIDENCE_NOT_UNIQUE:%s" % call_id)
        ref = str(rows[0].get("content_ref") or "")
        if not ref.startswith("state://"):
            raise CaseRuntimeError("CASE_PROVIDER_CALL_CONTENT_REF_INVALID:%s" % call_id)
        path = self.state_root / ref[len("state://"):]
        if not path.is_file():
            raise CaseRuntimeError("CASE_PROVIDER_CALL_PAYLOAD_MISSING:%s" % call_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _sha(payload) != str(rows[0].get("content_hash") or ""):
            raise CaseRuntimeError("CASE_PROVIDER_CALL_PAYLOAD_HASH_MISMATCH:%s" % call_id)
        response = payload.get("response")
        if not isinstance(response, dict):
            raise CaseRuntimeError("CASE_PROVIDER_REPLAY_RESPONSE_INVALID:%s" % call_id)
        return dict(response)

    def call(self, capability: str, request: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        capability = str(capability).upper()
        call_id = self._call_id(capability, request)
        replay = self._existing(call_id)
        evidence_id = "EVD-" + call_id
        if replay is not None:
            return replay, evidence_id

        provider = self.registry.get(capability)
        env = dict(os.environ)
        for key, value in provider["environment"].items():
            env[str(key)] = str(value)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "provider_id": provider["provider_id"],
            "capability": capability,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "attempt_id": self.attempt_id,
            "request": request,
        }
        try:
            proc = subprocess.run(
                provider["command"],
                input=_canonical(envelope),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=max(1, int(provider["timeout_seconds"])),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CaseRuntimeError("CASE_PROVIDER_EXECUTION_FAILED:%s:%s" % (capability, exc)) from exc
        stdout = _decode(proc.stdout or b"")
        stderr = _decode(proc.stderr or b"")
        if proc.returncode != 0:
            raise CaseRuntimeError("CASE_PROVIDER_NONZERO:%s:%s:%s" % (capability, proc.returncode, stderr[-1000:]))
        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CaseRuntimeError("CASE_PROVIDER_RESPONSE_INVALID_JSON:%s" % capability) from exc
        if not isinstance(response, dict) or not isinstance(response.get("success"), bool):
            raise CaseRuntimeError("CASE_PROVIDER_RESPONSE_CONTRACT_INVALID:%s" % capability)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "call_id": call_id,
            "provider_id": provider["provider_id"],
            "capability": capability,
            "request": request,
            "response": response,
            "exit_code": proc.returncode,
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        }
        target, digest = _write_immutable_json(
            self.state_root,
            Path(_safe_token(self.mission_id)) / _safe_token(self.attempt_id) / "provider-calls" / (call_id + ".json"),
            payload,
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=self.mission_id,
            kind=PROVIDER_CALL_KIND,
            source_ref="provider://%s/%s" % (_safe_token(provider["provider_id"]), capability),
            content_ref=_state_ref(self.state_root, target),
            subject_refs=[self.task_id, self.attempt_id, call_id, capability],
            content_hash=digest,
        )
        append_entity(self.truth, evidence, release_id=self.release_id, artifact_version=1)
        return dict(response), evidence.evidence_id


class HumanGateService:
    """Human approval is intentionally not exposed as an MCP Agent tool."""

    def __init__(self, truth: TruthRuntime, state_root: Path, *, mission_id: str, task_id: str, attempt_id: str) -> None:
        self.truth = truth
        self.state_root = state_root.resolve()
        self.mission_id = mission_id
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.release_id = _mission_release(truth, mission_id)

    def request_db_create(self, requirement: Mapping[str, Any], target_id: str) -> str:
        scope = {
            "action": "DB_CREATE",
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "requirement_id": requirement["id"],
            "selectors": requirement["selectors"],
            "target_id": target_id,
        }
        scope_hash = _sha(scope)
        request_id = "HGREQ-" + scope_hash[:24]
        existing = [
            row for row in self.truth.query("rc7_evidence", mission_id=self.mission_id)
            if row.get("kind") == HUMAN_GATE_REQUEST_KIND and request_id in list(row.get("subject_refs") or [])
        ]
        if not existing:
            target, digest = _write_immutable_json(
                self.state_root,
                Path(_safe_token(self.mission_id)) / _safe_token(self.attempt_id) / "human-gates" / (request_id + ".json"),
                scope,
            )
            append_entity(
                self.truth,
                Evidence(
                    evidence_id="EVD-" + request_id,
                    mission_id=self.mission_id,
                    kind=HUMAN_GATE_REQUEST_KIND,
                    source_ref="runtime://case-runtime/human-gate/db-create",
                    content_ref=_state_ref(self.state_root, target),
                    subject_refs=[self.task_id, self.attempt_id, request_id, str(requirement["id"]), scope_hash],
                    content_hash=digest,
                ),
                release_id=self.release_id,
                artifact_version=1,
            )
        return request_id

    def approval_for(self, request_id: str) -> Optional[str]:
        rows = [
            row for row in self.truth.query("rc7_evidence", mission_id=self.mission_id)
            if row.get("kind") == HUMAN_GATE_APPROVAL_KIND and request_id in list(row.get("subject_refs") or [])
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise CaseRuntimeError("HUMAN_GATE_APPROVAL_NOT_UNIQUE:%s" % request_id)
        return str(rows[0].get("evidence_id") or "")

    def approve(self, request_id: str, *, actor_ref: str, reason: str) -> str:
        actor_ref = str(actor_ref or "").strip()
        reason = str(reason or "").strip()
        if not actor_ref or not reason:
            raise CaseRuntimeError("HUMAN_GATE_ACTOR_AND_REASON_REQUIRED")
        requests = [
            row for row in self.truth.query("rc7_evidence", mission_id=self.mission_id)
            if row.get("kind") == HUMAN_GATE_REQUEST_KIND and request_id in list(row.get("subject_refs") or [])
        ]
        if len(requests) != 1:
            raise CaseRuntimeError("HUMAN_GATE_REQUEST_NOT_UNIQUE:%s" % request_id)
        approval_id = "HGAPP-" + hashlib.sha256((request_id + "\x1f" + actor_ref).encode("utf-8")).hexdigest()[:24]
        existing = self.approval_for(request_id)
        if existing:
            return existing
        payload = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "actor_ref": actor_ref,
            "reason": reason,
            "approved_at": int(time.time()),
        }
        target, digest = _write_immutable_json(
            self.state_root,
            Path(_safe_token(self.mission_id)) / _safe_token(self.attempt_id) / "human-gates" / (approval_id + ".json"),
            payload,
        )
        evidence = Evidence(
            evidence_id="EVD-" + approval_id,
            mission_id=self.mission_id,
            kind=HUMAN_GATE_APPROVAL_KIND,
            source_ref="human://%s" % _safe_token(actor_ref),
            content_ref=_state_ref(self.state_root, target),
            subject_refs=[self.task_id, self.attempt_id, request_id, approval_id],
            content_hash=digest,
        )
        append_entity(self.truth, evidence, release_id=self.release_id, artifact_version=1)
        return evidence.evidence_id


class CasePreparationService:
    def __init__(self, truth: TruthRuntime, state_root: Path, *, provider_config: Optional[Path] = None) -> None:
        self.truth = truth
        self.state_root = state_root.resolve()
        self.registry = ProviderRegistry(provider_config)

    def plan(self, *, mission_id: str, task_id: str, worker_id: str, case: Dict[str, Any], attempt_id: str, target_id: str) -> Dict[str, Any]:
        validate_call_context(self.truth, mission_id=mission_id, task_id=task_id, worker_id=worker_id)
        plan = PreparationSpecParser().parse(case)
        required = set("PRECONDITION_%s" % item["type"] for item in plan.preconditions)
        for item in plan.initial_state_requirements + plan.input_data_requirements:
            for strategy in item["allowed_strategies"]:
                required.add("DATA_%s" % strategy)
        if plan.initial_state_requirements or plan.input_data_requirements:
            required.add("DATA_VERIFY")
        available = set(self.registry.providers)
        return {
            "status": "PASS",
            "attempt_id": attempt_id,
            "target_id": target_id,
            "tc_id": plan.tc_id,
            "required_capabilities": sorted(required),
            "available_capabilities": sorted(required.intersection(available)),
            "field_required_capabilities": sorted(required.difference(available)),
            "db_human_gate_required_if_selected": any(
                "DB_CREATE" in item["allowed_strategies"]
                for item in plan.initial_state_requirements + plan.input_data_requirements
            ),
        }

    def _prepared_evidence(self, mission_id: str, task_id: str, attempt_id: str) -> Optional[Mapping[str, object]]:
        rows = [
            row for row in self.truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == PREPARED_ATTEMPT_KIND
            and task_id in list(row.get("subject_refs") or [])
            and attempt_id in list(row.get("subject_refs") or [])
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise CaseRuntimeError("PREPARED_ATTEMPT_EVIDENCE_NOT_UNIQUE:%s" % attempt_id)
        return rows[0]

    def _load_prepared(self, evidence: Mapping[str, object]) -> Dict[str, Any]:
        ref = str(evidence.get("content_ref") or "")
        if not ref.startswith("state://"):
            raise CaseRuntimeError("PREPARED_ATTEMPT_CONTENT_REF_INVALID")
        path = self.state_root / ref[len("state://"):]
        if not path.is_file():
            raise CaseRuntimeError("PREPARED_ATTEMPT_PAYLOAD_MISSING")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _sha(payload) != str(evidence.get("content_hash") or ""):
            raise CaseRuntimeError("PREPARED_ATTEMPT_PAYLOAD_HASH_MISMATCH")
        return payload

    def prepare(self, *, mission_id: str, task_id: str, worker_id: str, case: Dict[str, Any], attempt_id: str, target_id: str) -> Dict[str, Any]:
        validate_call_context(self.truth, mission_id=mission_id, task_id=task_id, worker_id=worker_id)
        existing = self._prepared_evidence(mission_id, task_id, attempt_id)
        if existing is not None:
            return {"status": "PREPARED", "prepared_attempt": self._load_prepared(existing), "evidence_id": existing["evidence_id"], "replayed": True}

        executor = ProviderExecutor(self.truth, self.state_root, self.registry, mission_id=mission_id, task_id=task_id, worker_id=worker_id, attempt_id=attempt_id)
        gates = HumanGateService(self.truth, self.state_root, mission_id=mission_id, task_id=task_id, attempt_id=attempt_id)
        pending_gate_requests = []

        def precondition(spec: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            response, evidence_id = executor.call("PRECONDITION_%s" % spec["type"], {"spec": spec, "context": context})
            return {"success": response["success"], "evidence_ref": evidence_id, "detail": response}

        def strategy(name: str):
            def invoke(requirement: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                try:
                    response, evidence_id = executor.call("DATA_%s" % name, {"requirement": requirement, "context": context})
                except CaseRuntimeFieldRequired as exc:
                    # Missing one allowed strategy is not terminal; PreparationRuntime
                    # must be allowed to try the next governed strategy in order.
                    return {"success": False, "reason": str(exc)}
                return {
                    "success": response["success"],
                    "binding": response.get("binding"),
                    "tool_call_ref": evidence_id,
                    "evidence_ref": evidence_id,
                    "reason": response.get("reason"),
                }
            return invoke

        def verify(requirement: Dict[str, Any], binding: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            response, evidence_id = executor.call("DATA_VERIFY", {"requirement": requirement, "binding": binding, "context": context})
            return {"success": response["success"], "evidence_ref": evidence_id}

        def human_gate(request: Dict[str, Any]) -> Optional[str]:
            requirement = {"id": request["requirement_id"], "selectors": request["selectors"]}
            request_id = gates.request_db_create(requirement, str(request.get("target_id") or target_id))
            approval = gates.approval_for(request_id)
            if not approval:
                pending_gate_requests.append(request_id)
                return None
            return approval

        runtime = PreparationRuntime(
            precondition_resolvers={name: (lambda spec, context, _name=name: precondition(spec, context)) for name in ("ENVIRONMENT", "AUTH", "BUSINESS_STATE", "DATA", "DEPENDENCY")},
            data_strategies={name: strategy(name) for name in ("REUSE_EXISTING", "DERIVE", "API_CREATE", "UI_CREATE", "DB_CREATE", "FIXTURE", "MOCK")},
            data_verifier=verify,
            human_gate=human_gate,
        )
        try:
            prepared = runtime.prepare(case=case, attempt_id=attempt_id, target_id=target_id)
        except CaseRuntimeFieldRequired as exc:
            return {"status": "FIELD_REQUIRED", "attempt_id": attempt_id, "field_required_capability": exc.capability, "provider_summary": self.registry.summary()}
        except PreparationContractError as exc:
            reason = str(exc)
            if reason.startswith("HUMAN_GATE_DENIED:") or reason.startswith("HUMAN_GATE_REQUIRED:"):
                return {"status": "HUMAN_GATE_REQUIRED", "attempt_id": attempt_id, "reason": reason, "gate_request_ids": sorted(set(pending_gate_requests))}
            if "FIELD_PROVIDER_REQUIRED:" in reason:
                capability = reason.split("FIELD_PROVIDER_REQUIRED:", 1)[1].split(":", 1)[0]
                return {"status": "FIELD_REQUIRED", "attempt_id": attempt_id, "reason": reason, "field_required_capability": capability, "provider_summary": self.registry.summary()}
            return {"status": "BLOCKED_PREPARATION", "attempt_id": attempt_id, "reason": reason}

        payload = asdict(prepared)
        target, digest = _write_immutable_json(self.state_root, Path(_safe_token(mission_id)) / _safe_token(attempt_id) / "prepared-attempt.json", payload)
        evidence_id = "EVD-PREPARED-" + hashlib.sha256((mission_id + "\x1f" + task_id + "\x1f" + attempt_id + "\x1f" + digest).encode("utf-8")).hexdigest()[:24]
        append_entity(
            self.truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id=mission_id,
                kind=PREPARED_ATTEMPT_KIND,
                source_ref="runtime://case-runtime/preparation",
                content_ref=_state_ref(self.state_root, target),
                subject_refs=[task_id, worker_id, attempt_id, prepared.tc_id, prepared.target_id],
                content_hash=digest,
            ),
            release_id=_mission_release(self.truth, mission_id),
            artifact_version=1,
        )
        return {"status": "PREPARED", "prepared_attempt": payload, "evidence_id": evidence_id, "replayed": False}

    def require_prepared(self, *, mission_id: str, task_id: str, prepared_attempt: Mapping[str, Any]) -> Mapping[str, object]:
        attempt_id = str(prepared_attempt.get("attempt_id") or "").strip()
        if not attempt_id:
            raise CaseRuntimeError("PREPARED_ATTEMPT_ID_REQUIRED")
        evidence = self._prepared_evidence(mission_id, task_id, attempt_id)
        if evidence is None:
            raise CaseRuntimeError("DURABLE_PREPARED_ATTEMPT_REQUIRED:%s" % attempt_id)
        durable = self._load_prepared(evidence)
        if durable != dict(prepared_attempt):
            raise CaseRuntimeError("PREPARED_ATTEMPT_DOES_NOT_MATCH_DURABLE_R1_EVIDENCE:%s" % attempt_id)
        if str(durable.get("status") or "") != "PREPARED":
            raise CaseRuntimeError("PREPARED_ATTEMPT_STATUS_INVALID:%s" % attempt_id)
        return evidence


def approve_gate(*, r1_path: Path, state_root: Path, mission_id: str, task_id: str, attempt_id: str, request_id: str, actor_ref: str, reason: str) -> Dict[str, Any]:
    truth = TruthRuntime(r1_path.resolve())
    service = HumanGateService(truth, state_root, mission_id=mission_id, task_id=task_id, attempt_id=attempt_id)
    evidence_id = service.approve(request_id, actor_ref=actor_ref, reason=reason)
    return {"status": "APPROVED", "request_id": request_id, "evidence_id": evidence_id, "actor_ref": actor_ref}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RC7 trusted Human Gate operator surface")
    sub = parser.add_subparsers(dest="command")
    approve = sub.add_parser("approve-db", help="Approve one previously emitted DB_CREATE Human Gate request")
    approve.add_argument("--r1", required=True)
    approve.add_argument("--state-root", required=True)
    approve.add_argument("--mission-id", required=True)
    approve.add_argument("--task-id", required=True)
    approve.add_argument("--attempt-id", required=True)
    approve.add_argument("--request-id", required=True)
    approve.add_argument("--actor-ref", required=True)
    approve.add_argument("--reason", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command != "approve-db":
            raise CaseRuntimeError("CASE_RUNTIME_COMMAND_REQUIRED")
        result = approve_gate(
            r1_path=Path(args.r1),
            state_root=Path(args.state_root),
            mission_id=args.mission_id,
            task_id=args.task_id,
            attempt_id=args.attempt_id,
            request_id=args.request_id,
            actor_ref=args.actor_ref,
            reason=args.reason,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
