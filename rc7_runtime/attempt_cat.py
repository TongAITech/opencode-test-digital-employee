"""Attempt-scoped CAT query runtime for RC7 failure diagnosis.

CAT results supplied by an Agent are never trusted. Runtime validates the
current failed Attempt from R1, the dynamic CAT policy, correlation scope and
deployment-bound BANK_CAT_QUERY provider before persisting immutable evidence.
"""
from __future__ import annotations

import hashlib
import json
import locale
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.diagnosis import CATPolicy, CorrelationScope
from rc6_runtime.truth import TruthRuntime

from .case_runtime import ProviderRegistry
from .models import Evidence
from .truth_overlay import append_entity


ATTEMPT_CAT_QUERY_KIND = "ATTEMPT_CAT_QUERY"
CAPABILITY = "BANK_CAT_QUERY"
SCHEMA_VERSION = "pfc.aitest.rc7.attempt-cat-query.v2"
_PROVIDER_CONFIG_ENVS = ("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", "PFC_RC7_CASE_PROVIDER_CONFIG")
_SECRET_TOKENS = (
    "password", "passwd", "secret", "token", "authorization", "credential",
    "cookie", "session_cookie", "access_key", "private_key",
)
BUSINESS_ACTION_STATES = frozenset({
    "UNKNOWN",
    "NOT_DISPATCHED",
    "DISPATCH_CONFIRMED",
    "BACKEND_PROCESSING_CONFIRMED",
})


class AttemptCatError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe(value: str) -> str:
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


def _reject_secrets(value: object, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).lower().replace("-", "_")
            if any(token in key for token in _SECRET_TOKENS):
                raise AttemptCatError("ATTEMPT_CAT_SECRET_FIELD_FORBIDDEN:%s.%s" % (path, raw_key))
            _reject_secrets(child, "%s.%s" % (path, raw_key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secrets(child, "%s[%d]" % (path, index))


def _config_path(state_root: Path) -> Optional[Path]:
    for key in _PROVIDER_CONFIG_ENVS:
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser().resolve()
    home = os.environ.get("PFC_AITEST_HOME")
    if home:
        candidate = Path(home).expanduser().resolve() / "state" / "bank-field-providers.json"
        if candidate.is_file():
            return candidate
    candidate = state_root.resolve().parent / "state" / "bank-field-providers.json"
    return candidate if candidate.is_file() else None


def _correlation(raw: Mapping[str, Any]) -> CorrelationScope:
    if not isinstance(raw, Mapping):
        raise AttemptCatError("ATTEMPT_CAT_CORRELATION_REQUIRED")
    applications = raw.get("applications")
    if not isinstance(applications, (list, tuple)):
        raise AttemptCatError("ATTEMPT_CAT_APPLICATIONS_REQUIRED")
    try:
        scope = CorrelationScope(
            applications=tuple(str(x) for x in applications),
            window_start=int(raw["window_start"]),
            window_end=int(raw["window_end"]),
            request_id=str(raw["request_id"]) if raw.get("request_id") else None,
            trace_id=str(raw["trace_id"]) if raw.get("trace_id") else None,
            business_id=str(raw["business_id"]) if raw.get("business_id") else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AttemptCatError("ATTEMPT_CAT_CORRELATION_INVALID") from exc
    CATPolicy().validate_scope(scope)
    return scope


def _scope_payload(scope: CorrelationScope) -> Dict[str, Any]:
    return {
        "applications": list(scope.applications),
        "window_start": scope.window_start,
        "window_end": scope.window_end,
        **scope.identifiers(),
    }


def cat_required_for_context(context: Mapping[str, Any]) -> bool:
    """Mirror the RC7.1 dynamic CAT policy at the R1 trust boundary."""
    if not isinstance(context, Mapping):
        raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_REQUIRED")
    if not bool(context.get("real_action_executed")):
        return False
    layer = str(context.get("layer") or "").upper()
    state = str(context.get("business_action_state") or "UNKNOWN").upper()
    if state not in BUSINESS_ACTION_STATES:
        raise AttemptCatError("ATTEMPT_CAT_BUSINESS_ACTION_STATE_INVALID:%s" % state)
    if layer in {"L1", "L2"}:
        return bool(context.get("remote_integration"))
    if layer == "L3":
        return True
    if layer in {"L4", "L5", "L6", "L7"}:
        return state != "NOT_DISPATCHED"
    return bool(context.get("remote_integration"))


class AttemptCatQueryService:
    def __init__(self, truth: TruthRuntime, state_root: Path) -> None:
        self.truth = truth
        self.state_root = Path(state_root).resolve()

    def _attempt(self, attempt_id: str, target_id: str) -> Mapping[str, object]:
        rows = self.truth.query("execution_attempt", attempt_id=attempt_id)
        if len(rows) != 1:
            raise AttemptCatError("ATTEMPT_CAT_EXECUTION_ATTEMPT_NOT_UNIQUE")
        attempt = rows[0]
        if str(attempt.get("status") or "").upper() != "FAIL":
            raise AttemptCatError("ATTEMPT_CAT_REQUIRES_FAILED_ATTEMPT")
        if str(attempt.get("target_id") or "") != target_id:
            raise AttemptCatError("ATTEMPT_CAT_TARGET_MISMATCH")
        return attempt

    def _validate_task(self, mission_id: str, task_id: str) -> str:
        rows = self.truth.query("rc7_task", task_id=task_id)
        if len(rows) != 1:
            raise AttemptCatError("ATTEMPT_CAT_TASK_NOT_UNIQUE")
        task = rows[0]
        if str(task.get("mission_id") or "") != mission_id or str(task.get("node") or "") != "EXECUTION":
            raise AttemptCatError("ATTEMPT_CAT_REQUIRES_EXECUTION_TASK")
        missions = self.truth.query("rc7_mission", mission_id=mission_id)
        if len(missions) != 1:
            raise AttemptCatError("ATTEMPT_CAT_MISSION_NOT_UNIQUE")
        release_id = str(missions[0].get("release_id") or "")
        if not release_id:
            raise AttemptCatError("ATTEMPT_CAT_RELEASE_ID_REQUIRED")
        return release_id

    @staticmethod
    def _identity(mission_id: str, task_id: str, attempt_id: str, target_id: str, scope: CorrelationScope) -> str:
        return "CATQ-" + hashlib.sha256(_canonical({
            "mission_id": mission_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "target_id": target_id,
            "scope": _scope_payload(scope),
        })).hexdigest()[:24]

    @staticmethod
    def _policy_payload(context: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "layer": str(context.get("layer") or "").upper(),
            "real_action_executed": bool(context.get("real_action_executed")),
            "remote_integration": bool(context.get("remote_integration")),
            "business_action_state": str(context.get("business_action_state") or "UNKNOWN").upper(),
        }

    def _validated_context(self, attempt: Mapping[str, object], *, attempt_id: str, target_id: str, failure_context: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(failure_context, Mapping):
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_REQUIRED")
        raw_attempt_id = failure_context.get("attempt_id")
        if raw_attempt_id is not None and str(raw_attempt_id) != attempt_id:
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_ATTEMPT_MISMATCH")
        raw_target_id = failure_context.get("target_id")
        if raw_target_id is not None and str(raw_target_id) != target_id:
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_TARGET_MISMATCH")
        layer = str(failure_context.get("layer") or "").upper()
        attempt_layer = str(attempt.get("layer") or "").upper()
        if not layer:
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_LAYER_REQUIRED")
        if layer != attempt_layer:
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_LAYER_MISMATCH")
        policy = self._policy_payload(failure_context)
        if policy["business_action_state"] not in BUSINESS_ACTION_STATES:
            raise AttemptCatError("ATTEMPT_CAT_BUSINESS_ACTION_STATE_INVALID:%s" % policy["business_action_state"])
        return {**dict(failure_context), **policy, "attempt_id": attempt_id, "target_id": target_id}

    def _existing(self, mission_id: str, query_id: str, *, task_id: str, attempt_id: str, target_id: str, scope: CorrelationScope, policy: Mapping[str, Any]) -> Optional[Tuple[Mapping[str, object], Dict[str, Any]]]:
        rows = [
            row for row in self.truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == ATTEMPT_CAT_QUERY_KIND and query_id in list(row.get("subject_refs") or [])
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise AttemptCatError("ATTEMPT_CAT_EVIDENCE_NOT_UNIQUE")
        ref = str(rows[0].get("content_ref") or "")
        if not ref.startswith("state://"):
            raise AttemptCatError("ATTEMPT_CAT_CONTENT_REF_INVALID")
        path = self.state_root / ref[len("state://"):]
        if not path.is_file():
            raise AttemptCatError("ATTEMPT_CAT_PAYLOAD_MISSING")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AttemptCatError("ATTEMPT_CAT_PAYLOAD_INVALID") from exc
        if _sha(payload) != str(rows[0].get("content_hash") or ""):
            raise AttemptCatError("ATTEMPT_CAT_PAYLOAD_HASH_MISMATCH")
        expected = {
            "query_id": query_id,
            "mission_id": mission_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "target_id": target_id,
            "correlation": _scope_payload(scope),
            "policy": dict(policy),
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise AttemptCatError("ATTEMPT_CAT_REPLAY_CONTEXT_MISMATCH:%s" % key)
        refs = payload.get("refs")
        if not isinstance(refs, dict):
            raise AttemptCatError("ATTEMPT_CAT_REPLAY_REFS_INVALID")
        for field in ("tool_call_ref", "evidence_ref", "cat_evidence_ref", "correlation_ref"):
            if not isinstance(refs.get(field), str) or not refs[field]:
                raise AttemptCatError("ATTEMPT_CAT_REPLAY_REF_REQUIRED:%s" % field)
        return rows[0], payload

    def _provider(self) -> Dict[str, Any]:
        config = _config_path(self.state_root)
        registry = ProviderRegistry(config)
        return registry.get(CAPABILITY)

    def query(self, *, mission_id: str, task_id: str, worker_id: str, attempt_id: str, target_id: str, correlation: Mapping[str, Any], failure_context: Mapping[str, Any]) -> Dict[str, Any]:
        mission_id = str(mission_id or "").strip()
        task_id = str(task_id or "").strip()
        worker_id = str(worker_id or "").strip()
        attempt_id = str(attempt_id or "").strip()
        target_id = str(target_id or "").strip()
        if not all((mission_id, task_id, worker_id, attempt_id, target_id)):
            raise AttemptCatError("ATTEMPT_CAT_CONTEXT_REQUIRED")
        release_id = self._validate_task(mission_id, task_id)
        attempt = self._attempt(attempt_id, target_id)
        current = self._validated_context(attempt, attempt_id=attempt_id, target_id=target_id, failure_context=failure_context)
        if not cat_required_for_context(current):
            raise AttemptCatError("ATTEMPT_CAT_NOT_REQUIRED_FOR_CURRENT_FAILURE:%s" % attempt_id)
        scope = _correlation(correlation)
        query_id = self._identity(mission_id, task_id, attempt_id, target_id, scope)
        policy = self._policy_payload(current)
        existing = self._existing(mission_id, query_id, task_id=task_id, attempt_id=attempt_id, target_id=target_id, scope=scope, policy=policy)
        if existing is not None:
            row, payload = existing
            return {
                "status": "PASS",
                "query_id": query_id,
                "evidence_id": row["evidence_id"],
                "tool_call_ref": payload["refs"]["tool_call_ref"],
                "evidence_ref": payload["refs"]["evidence_ref"],
                "signals": dict(payload.get("signals") or {}),
                "replayed": True,
            }

        provider = self._provider()
        env = dict(os.environ)
        for key, value in provider["environment"].items():
            env[str(key)] = str(value)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "provider_id": provider["provider_id"],
            "capability": CAPABILITY,
            "mission_id": mission_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "attempt_id": attempt_id,
            "request": {
                "purpose": "RC7_ATTEMPT_FAILURE_DIAGNOSIS",
                "target_id": target_id,
                "correlation": _scope_payload(scope),
                "policy": policy,
            },
        }
        try:
            proc = subprocess.run(
                provider["command"], input=_canonical(envelope), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
                timeout=max(1, int(provider["timeout_seconds"])), check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AttemptCatError("ATTEMPT_CAT_PROVIDER_EXECUTION_FAILED:%s" % exc) from exc
        if proc.returncode != 0:
            raise AttemptCatError("ATTEMPT_CAT_PROVIDER_NONZERO:%d:%s" % (proc.returncode, _decode(proc.stderr or b"")[-1000:]))
        try:
            response = json.loads(_decode(proc.stdout or b""))
        except json.JSONDecodeError as exc:
            raise AttemptCatError("ATTEMPT_CAT_PROVIDER_INVALID_JSON") from exc
        if not isinstance(response, dict):
            raise AttemptCatError("ATTEMPT_CAT_PROVIDER_RESPONSE_NOT_OBJECT")
        _reject_secrets(response)
        if response.get("success") is not True or response.get("target_verified") is not True:
            raise AttemptCatError("ATTEMPT_CAT_PROVIDER_NOT_VERIFIED")
        refs: Dict[str, str] = {}
        for field in ("tool_call_ref", "evidence_ref", "cat_evidence_ref", "correlation_ref"):
            value = response.get(field)
            if not isinstance(value, str) or not value.strip():
                raise AttemptCatError("ATTEMPT_CAT_PROVIDER_REF_REQUIRED:%s" % field)
            refs[field] = value.strip()
        signals = response.get("signals") or {}
        if not isinstance(signals, dict):
            raise AttemptCatError("ATTEMPT_CAT_SIGNALS_NOT_OBJECT")
        _reject_secrets(signals)
        sanitized = {
            "schema_version": SCHEMA_VERSION,
            "query_id": query_id,
            "mission_id": mission_id,
            "release_id": release_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "attempt_id": attempt_id,
            "target_id": target_id,
            "provider_id": provider["provider_id"],
            "correlation": _scope_payload(scope),
            "policy": policy,
            "refs": refs,
            "signals": signals,
        }
        body = _canonical(sanitized)
        digest = hashlib.sha256(body).hexdigest()
        path = self.state_root / "attempt-cat" / _safe(mission_id) / _safe(attempt_id) / (query_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != body:
            raise AttemptCatError("ATTEMPT_CAT_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)
        evidence = Evidence(
            evidence_id="EVD-" + query_id,
            mission_id=mission_id,
            kind=ATTEMPT_CAT_QUERY_KIND,
            source_ref="provider://%s/%s" % (_safe(str(provider["provider_id"])), CAPABILITY),
            content_ref="state://" + path.relative_to(self.state_root).as_posix(),
            subject_refs=[task_id, worker_id, attempt_id, target_id, query_id, refs["tool_call_ref"], refs["evidence_ref"], refs["cat_evidence_ref"], refs["correlation_ref"]],
            content_hash=digest,
        )
        append_entity(self.truth, evidence, release_id=release_id, artifact_version=1)
        return {
            "status": "PASS", "query_id": query_id, "evidence_id": evidence.evidence_id,
            "tool_call_ref": refs["tool_call_ref"], "evidence_ref": refs["evidence_ref"],
            "signals": signals, "replayed": False,
        }

    def require_for_failure_context(self, *, mission_id: str, task_id: str, worker_id: str, failure_context: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        mission_id = str(mission_id or "").strip()
        task_id = str(task_id or "").strip()
        worker_id = str(worker_id or "").strip()
        if not all((mission_id, task_id, worker_id)):
            raise AttemptCatError("ATTEMPT_CAT_CONTEXT_REQUIRED")
        self._validate_task(mission_id, task_id)
        attempt_id = str(failure_context.get("attempt_id") or "").strip()
        target_id = str(failure_context.get("target_id") or "").strip()
        if not attempt_id or not target_id:
            raise AttemptCatError("ATTEMPT_CAT_FAILURE_CONTEXT_IDENTITY_REQUIRED")
        attempt = self._attempt(attempt_id, target_id)
        current = self._validated_context(attempt, attempt_id=attempt_id, target_id=target_id, failure_context=failure_context)
        if not cat_required_for_context(current):
            return None
        correlation = failure_context.get("correlation")
        if not isinstance(correlation, Mapping):
            raise AttemptCatError("ATTEMPT_CAT_CORRELATION_REQUIRED")
        scope = _correlation(correlation)
        query_id = self._identity(mission_id, task_id, attempt_id, target_id, scope)
        policy = self._policy_payload(current)
        existing = self._existing(mission_id, query_id, task_id=task_id, attempt_id=attempt_id, target_id=target_id, scope=scope, policy=policy)
        if existing is None:
            raise AttemptCatError("ATTEMPT_CAT_QUERY_REQUIRED_BEFORE_FAILURE_DIAGNOSE:%s" % attempt_id)
        row, payload = existing
        refs = payload["refs"]
        return {
            "cat_required": True,
            "cat_queried": True,
            "cat_query_evidence_id": row["evidence_id"],
            "tool_call_ref": refs["tool_call_ref"],
            "evidence_ref": refs["evidence_ref"],
            "signals": dict(payload.get("signals") or {}),
        }
