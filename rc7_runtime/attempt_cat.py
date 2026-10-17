"""Attempt-scoped CAT query runtime for RC7 failure diagnosis.

CAT results supplied by an Agent are never trusted for contracted graph-v2
Missions. The Runtime validates CAT policy/scope, launches the deployment-bound
BANK_CAT_QUERY provider, rejects secrets before persistence, and stores a
sanitized immutable proof tied to the failed execution Attempt.
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

from .case_runtime import CaseRuntimeError, ProviderRegistry
from .models import Evidence
from .truth_overlay import append_entity


ATTEMPT_CAT_QUERY_KIND = "ATTEMPT_CAT_QUERY"
CAPABILITY = "BANK_CAT_QUERY"
SCHEMA_VERSION = "pfc.aitest.rc7.attempt-cat-query.v1"
_PROVIDER_CONFIG_ENVS = ("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", "PFC_RC7_CASE_PROVIDER_CONFIG")
_SECRET_TOKENS = (
    "password", "passwd", "secret", "token", "authorization", "credential",
    "cookie", "session_cookie", "access_key", "private_key",
)


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
    if not isinstance(applications, list):
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


def cat_required_for_context(context: Mapping[str, Any]) -> bool:
    layer = str(context.get("layer") or "").upper()
    return layer in {"L3", "L5"} or (layer == "L1" and bool(context.get("remote_integration")))


class AttemptCatQueryService:
    def __init__(self, truth: TruthRuntime, state_root: Path) -> None:
        self.truth = truth
        self.state_root = Path(state_root).resolve()

    def _attempt(self, attempt_id: str, target_id: str) -> Mapping[str, object]:
        rows = self.truth.query("execution_attempt", attempt_id=attempt_id)
        if len(rows) != 1:
            raise AttemptCatError("ATTEMPT_CAT_EXECUTION_ATTEMPT_NOT_UNIQUE")
        attempt = rows[0]
        if str(attempt.get("status") or "") != "FAIL":
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
            "scope": {
                "applications": list(scope.applications),
                "window_start": scope.window_start,
                "window_end": scope.window_end,
                **scope.identifiers(),
            },
        })).hexdigest()[:24]

    def _existing(self, mission_id: str, query_id: str) -> Optional[Tuple[Mapping[str, object], Dict[str, Any]]]:
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _sha(payload) != str(rows[0].get("content_hash") or ""):
            raise AttemptCatError("ATTEMPT_CAT_PAYLOAD_HASH_MISMATCH")
        return rows[0], payload

    def _provider(self) -> Tuple[Dict[str, Any], ProviderRegistry]:
        config = _config_path(self.state_root)
        registry = ProviderRegistry(config)
        return registry.get(CAPABILITY), registry

    def query(
        self,
        *,
        mission_id: str,
        task_id: str,
        worker_id: str,
        attempt_id: str,
        target_id: str,
        correlation: Mapping[str, Any],
    ) -> Dict[str, Any]:
        mission_id = str(mission_id or "").strip()
        task_id = str(task_id or "").strip()
        worker_id = str(worker_id or "").strip()
        attempt_id = str(attempt_id or "").strip()
        target_id = str(target_id or "").strip()
        if not all((mission_id, task_id, worker_id, attempt_id, target_id)):
            raise AttemptCatError("ATTEMPT_CAT_CONTEXT_REQUIRED")
        release_id = self._validate_task(mission_id, task_id)
        attempt = self._attempt(attempt_id, target_id)
        if not cat_required_for_context({"layer": attempt.get("layer"), "remote_integration": False}):
            # L1 remote-integration requirement is supplied by FailureContext,
            # not persisted in the generic execution-attempt contract; query()
            # may still be invoked for L1 only when the caller explicitly uses
            # require_for_failure_context below.
            if str(attempt.get("layer") or "").upper() != "L1":
                raise AttemptCatError("ATTEMPT_CAT_NOT_REQUIRED_FOR_LAYER:%s" % str(attempt.get("layer") or ""))
        scope = _correlation(correlation)
        query_id = self._identity(mission_id, task_id, attempt_id, target_id, scope)
        existing = self._existing(mission_id, query_id)
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

        provider, _ = self._provider()
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
                "correlation": {
                    "applications": list(scope.applications),
                    "window_start": scope.window_start,
                    "window_end": scope.window_end,
                    **scope.identifiers(),
                },
            },
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
        refs = {}
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
            "correlation": envelope["request"]["correlation"],
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
            subject_refs=[task_id, worker_id, attempt_id, target_id, query_id, refs["tool_call_ref"], refs["evidence_ref"], refs["correlation_ref"]],
            content_hash=digest,
        )
        append_entity(self.truth, evidence, release_id=release_id, artifact_version=1)
        return {
            "status": "PASS",
            "query_id": query_id,
            "evidence_id": evidence.evidence_id,
            "tool_call_ref": refs["tool_call_ref"],
            "evidence_ref": refs["evidence_ref"],
            "signals": signals,
            "replayed": False,
        }

    def require_for_failure_context(
        self,
        *,
        mission_id: str,
        task_id: str,
        worker_id: str,
        failure_context: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        required = cat_required_for_context(failure_context)
        if not required:
            return None
        attempt_id = str(failure_context.get("attempt_id") or "").strip()
        target_id = str(failure_context.get("target_id") or "").strip()
        correlation = failure_context.get("correlation")
        if not isinstance(correlation, Mapping):
            raise AttemptCatError("ATTEMPT_CAT_CORRELATION_REQUIRED")
        scope = _correlation(correlation)
        query_id = self._identity(mission_id, task_id, attempt_id, target_id, scope)
        existing = self._existing(mission_id, query_id)
        if existing is None:
            raise AttemptCatError("ATTEMPT_CAT_QUERY_REQUIRED_BEFORE_FAILURE_DIAGNOSE:%s" % attempt_id)
        row, payload = existing
        refs = payload.get("refs") or {}
        return {
            "cat_required": True,
            "cat_queried": True,
            "cat_query_evidence_id": row["evidence_id"],
            "tool_call_ref": refs["tool_call_ref"],
            "evidence_ref": refs["evidence_ref"],
            "signals": dict(payload.get("signals") or {}),
        }
