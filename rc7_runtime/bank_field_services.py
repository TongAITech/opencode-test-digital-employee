"""Runtime-owned bank field service probes for RC7 Bank Final qualification.

These probes are not Agent-authored claims. The runtime launches deployment-
configured providers and only after validating a secret-free proof response does
it persist a sanitized immutable R1 capability receipt.

DB write qualification is intentionally Human-Gated. The first probe creates a
durable request and returns HUMAN_GATE_REQUIRED. Only an explicit operator
approval allows the write provider to run. The provider must also return
verification plus cleanup/rollback references so qualification never leaves a
probe write without recovery evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import rc6_runtime.agent_runtime  # noqa: F401 - installs WORKER_* R1 events
import rc6_runtime.execution_overlay  # noqa: F401 - installs execution closure R1 events
from rc6_runtime.truth import TruthRuntime

from .case_runtime import (
    HUMAN_GATE_APPROVAL_KIND,
    PROVIDER_CALL_KIND,
    HumanGateService,
    ProviderRegistry,
)
from .models import Evidence
from .session_continuity import install_session_overlay
from .truth_overlay import append_entity, install_rc7_truth_overlay


SCHEMA_VERSION = "pfc.aitest.rc7.bank-field-services.v1"
PROBE_KIND = "BANK_FIELD_SERVICE_PROBE"
PROBE_WORKER = "RC7-BANK-FIELD-QUALIFIER"
CAP_AUTH_4A = "BANK_AUTH_4A"
CAP_CAT = "BANK_CAT_QUERY"
CAP_DB_READ = "BANK_DB_READ"
CAP_DB_WRITE = "BANK_DB_WRITE"
REQUIRED_CAPABILITIES = (CAP_AUTH_4A, CAP_CAT, CAP_DB_READ, CAP_DB_WRITE)

_REQUIRED_RESPONSE_FIELDS = {
    CAP_AUTH_4A: ("auth_evidence_ref",),
    CAP_CAT: ("cat_evidence_ref", "correlation_ref"),
    CAP_DB_READ: ("read_evidence_ref",),
    CAP_DB_WRITE: ("write_evidence_ref", "verification_ref"),
}
_SECRET_KEY_TOKENS = (
    "password", "passwd", "secret", "token", "authorization", "credential",
    "cookie", "session_cookie", "access_key", "private_key",
)


class BankFieldServiceError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _install_overlays() -> None:
    install_rc7_truth_overlay()
    install_session_overlay()


def _release_id(truth: TruthRuntime, mission_id: str) -> str:
    rows = truth.query("rc7_mission", mission_id=mission_id)
    if len(rows) != 1:
        raise BankFieldServiceError("BANK_FIELD_MISSION_NOT_UNIQUE")
    value = str(rows[0].get("release_id") or "").strip()
    if not value:
        raise BankFieldServiceError("BANK_FIELD_RELEASE_ID_MISSING")
    return value


def _execution_task(truth: TruthRuntime, mission_id: str) -> Mapping[str, object]:
    rows = [
        row for row in truth.query("rc7_task", mission_id=mission_id)
        if str(row.get("node") or "") == "EXECUTION"
    ]
    if len(rows) != 1:
        raise BankFieldServiceError("BANK_FIELD_EXECUTION_TASK_NOT_UNIQUE:%d" % len(rows))
    return rows[0]


def _probe_attempt_id(mission_id: str, target_id: str) -> str:
    return "BANK-FIELD-PROBE-" + hashlib.sha256((mission_id + "\x1f" + target_id).encode("utf-8")).hexdigest()[:20]


def _reject_secret_payload(value: object, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).lower().replace("-", "_")
            if any(token in key for token in _SECRET_KEY_TOKENS):
                raise BankFieldServiceError("BANK_FIELD_PROVIDER_SECRET_FIELD_FORBIDDEN:%s.%s" % (path, raw_key))
            _reject_secret_payload(child, "%s.%s" % (path, raw_key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secret_payload(child, "%s[%d]" % (path, index))


def _required_ref(response: Mapping[str, Any], field: str, capability: str) -> str:
    value = response.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_REF_REQUIRED:%s:%s" % (capability, field))
    return value.strip()


def _validate_response(capability: str, response: Mapping[str, Any]) -> Dict[str, str]:
    _reject_secret_payload(response)
    if response.get("success") is not True:
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_REPORTED_FAILURE:%s" % capability)
    if response.get("target_verified") is not True:
        raise BankFieldServiceError("BANK_FIELD_TARGET_NOT_VERIFIED:%s" % capability)
    refs = {
        "tool_call_ref": _required_ref(response, "tool_call_ref", capability),
        "evidence_ref": _required_ref(response, "evidence_ref", capability),
    }
    for field in _REQUIRED_RESPONSE_FIELDS[capability]:
        refs[field] = _required_ref(response, field, capability)
    if capability == CAP_DB_WRITE:
        cleanup = response.get("cleanup_ref") or response.get("rollback_ref")
        if not isinstance(cleanup, str) or not cleanup.strip():
            raise BankFieldServiceError("BANK_FIELD_DB_WRITE_CLEANUP_OR_ROLLBACK_REQUIRED")
        refs["cleanup_or_rollback_ref"] = cleanup.strip()
    return refs


def _safe_token(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))
    return text[:120] or "unknown"


def _write_sanitized_probe(state_root: Path, mission_id: str, target_id: str, capability: str, payload: Mapping[str, Any]) -> Tuple[Path, str]:
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    target = (
        state_root
        / "bank-field-services"
        / _safe_token(mission_id)
        / _safe_token(target_id)
        / (capability.lower() + ".json")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != body:
        raise BankFieldServiceError("BANK_FIELD_PROBE_IMMUTABILITY_CONFLICT:%s" % capability)
    if not target.exists():
        target.write_bytes(body)
    return target, digest


def _probe_evidence_id(mission_id: str, target_id: str, capability: str, refs: Mapping[str, str]) -> str:
    return "EVD-BANK-SVC-" + _sha({
        "mission_id": mission_id,
        "target_id": target_id,
        "capability": capability,
        "refs": dict(refs),
    })[:24]


def _existing_probe(truth: TruthRuntime, mission_id: str, target_id: str, capability: str) -> Optional[Mapping[str, object]]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == PROBE_KIND
        and target_id in list(row.get("subject_refs") or [])
        and capability in list(row.get("subject_refs") or [])
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise BankFieldServiceError("BANK_FIELD_SERVICE_PROBE_NOT_UNIQUE:%s:%d" % (capability, len(rows)))
    return rows[0]


def _call_provider(
    registry: ProviderRegistry,
    *,
    capability: str,
    mission_id: str,
    task_id: str,
    attempt_id: str,
    target_id: str,
) -> Tuple[str, Dict[str, str]]:
    provider = registry.get(capability)
    env = dict(os.environ)
    for key, value in provider["environment"].items():
        env[str(key)] = str(value)
    request = {
        "schema_version": SCHEMA_VERSION,
        "provider_id": provider["provider_id"],
        "capability": capability,
        "mission_id": mission_id,
        "task_id": task_id,
        "worker_id": PROBE_WORKER,
        "attempt_id": attempt_id,
        "request": {
            "probe": True,
            "purpose": "RC7_BANK_FIELD_QUALIFICATION",
            "target_id": target_id,
            "cleanup_required": capability == CAP_DB_WRITE,
        },
    }
    try:
        proc = subprocess.run(
            provider["command"],
            input=_canonical(request),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=max(1, int(provider["timeout_seconds"])),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_EXECUTION_FAILED:%s:%s" % (capability, exc)) from exc
    stdout = _decode(proc.stdout or b"")
    stderr = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_NONZERO:%s:%d:%s" % (capability, proc.returncode, stderr[-1000:]))
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_INVALID_JSON:%s" % capability) from exc
    if not isinstance(response, dict):
        raise BankFieldServiceError("BANK_FIELD_PROVIDER_RESPONSE_NOT_OBJECT:%s" % capability)
    refs = _validate_response(capability, response)
    return str(provider["provider_id"]), refs


def _record_probe(
    truth: TruthRuntime,
    state_root: Path,
    *,
    mission_id: str,
    release_id: str,
    task_id: str,
    attempt_id: str,
    target_id: str,
    capability: str,
    provider_id: str,
    refs: Mapping[str, str],
    approval_evidence_id: Optional[str] = None,
) -> Evidence:
    evidence_id = _probe_evidence_id(mission_id, target_id, capability, refs)
    sanitized = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "release_id": release_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "target_id": target_id,
        "capability": capability,
        "provider_id": provider_id,
        "refs": dict(refs),
        "human_gate_approval_evidence_id": approval_evidence_id,
    }
    target, digest = _write_sanitized_probe(state_root, mission_id, target_id, capability, sanitized)
    subjects = [
        task_id,
        attempt_id,
        target_id,
        capability,
        "provider:%s" % provider_id,
        refs["tool_call_ref"],
        refs["evidence_ref"],
    ]
    if approval_evidence_id:
        subjects.append(approval_evidence_id)
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=mission_id,
        kind=PROBE_KIND,
        source_ref="provider://%s/%s" % (_safe_token(provider_id), capability),
        content_ref="state://" + target.relative_to(state_root).as_posix(),
        subject_refs=subjects,
        content_hash=digest,
    )
    if not truth.query("rc7_evidence", evidence_id=evidence_id):
        append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


def _db_gate(
    truth: TruthRuntime,
    state_root: Path,
    *,
    mission_id: str,
    task_id: str,
    attempt_id: str,
    target_id: str,
) -> Tuple[str, Optional[str]]:
    service = HumanGateService(
        truth,
        state_root,
        mission_id=mission_id,
        task_id=task_id,
        attempt_id=attempt_id,
    )
    request_id = service.request_db_create(
        {
            "id": "BANK-FIELD-DB-WRITE-PROBE",
            "selectors": {
                "purpose": "RC7_BANK_FIELD_QUALIFICATION",
                "capability": CAP_DB_WRITE,
                "cleanup_required": True,
            },
        },
        target_id,
    )
    return request_id, service.approval_for(request_id)


def probe_bank_services(
    *,
    r1_path: str,
    state_root: str,
    provider_config: str,
    mission_id: str,
    target_id: str,
) -> Dict[str, Any]:
    _install_overlays()
    truth = TruthRuntime(Path(r1_path).expanduser().resolve())
    state = Path(state_root).expanduser().resolve()
    registry = ProviderRegistry(Path(provider_config).expanduser().resolve())
    task = _execution_task(truth, mission_id)
    task_id = str(task["task_id"])
    release_id = _release_id(truth, mission_id)
    target_id = str(target_id or "").strip()
    if not target_id:
        raise BankFieldServiceError("BANK_FIELD_TARGET_ID_REQUIRED")
    attempt_id = _probe_attempt_id(mission_id, target_id)

    results: Dict[str, Dict[str, Any]] = {}
    gate_request_id: Optional[str] = None
    for capability in REQUIRED_CAPABILITIES:
        existing = _existing_probe(truth, mission_id, target_id, capability)
        if existing is not None:
            results[capability] = {
                "status": "PASS",
                "probe_evidence_id": existing["evidence_id"],
                "replayed": True,
            }
            continue

        approval_evidence_id: Optional[str] = None
        if capability == CAP_DB_WRITE:
            gate_request_id, approval_evidence_id = _db_gate(
                truth,
                state,
                mission_id=mission_id,
                task_id=task_id,
                attempt_id=attempt_id,
                target_id=target_id,
            )
            if not approval_evidence_id:
                results[capability] = {
                    "status": "HUMAN_GATE_REQUIRED",
                    "gate_request_id": gate_request_id,
                }
                continue
        try:
            provider_id, refs = _call_provider(
                registry,
                capability=capability,
                mission_id=mission_id,
                task_id=task_id,
                attempt_id=attempt_id,
                target_id=target_id,
            )
            evidence = _record_probe(
                truth,
                state,
                mission_id=mission_id,
                release_id=release_id,
                task_id=task_id,
                attempt_id=attempt_id,
                target_id=target_id,
                capability=capability,
                provider_id=provider_id,
                refs=refs,
                approval_evidence_id=approval_evidence_id,
            )
            results[capability] = {
                "status": "PASS",
                "probe_evidence_id": evidence.evidence_id,
                "tool_call_ref": refs["tool_call_ref"],
                "evidence_ref": refs["evidence_ref"],
                "human_gate_approval_evidence_id": approval_evidence_id,
                "replayed": False,
            }
        except Exception as exc:
            reason = str(exc)
            if reason.startswith("FIELD_PROVIDER_REQUIRED:"):
                results[capability] = {"status": "FIELD_REQUIRED", "reason": reason}
            else:
                results[capability] = {"status": "FAIL", "reason": reason}

    statuses = {row["status"] for row in results.values()}
    if "FAIL" in statuses:
        status = "FAIL"
    elif "FIELD_REQUIRED" in statuses:
        status = "FIELD_REQUIRED"
    elif "HUMAN_GATE_REQUIRED" in statuses:
        status = "HUMAN_GATE_REQUIRED"
    else:
        status = "PASS"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "mission_id": mission_id,
        "release_id": release_id,
        "task_id": task_id,
        "target_id": target_id,
        "probe_attempt_id": attempt_id,
        "provider_capabilities": registry.summary()["capabilities"],
        "capabilities": results,
        "db_write_gate_request_id": gate_request_id,
    }


def approve_db_write_probe(
    *,
    r1_path: str,
    state_root: str,
    mission_id: str,
    target_id: str,
    request_id: str,
    actor_ref: str,
    reason: str,
) -> Dict[str, Any]:
    _install_overlays()
    truth = TruthRuntime(Path(r1_path).expanduser().resolve())
    task = _execution_task(truth, mission_id)
    attempt_id = _probe_attempt_id(mission_id, target_id)
    gate = HumanGateService(
        truth,
        Path(state_root).expanduser().resolve(),
        mission_id=mission_id,
        task_id=str(task["task_id"]),
        attempt_id=attempt_id,
    )
    evidence_id = gate.approve(request_id, actor_ref=actor_ref, reason=reason)
    return {
        "status": "APPROVED",
        "mission_id": mission_id,
        "target_id": target_id,
        "request_id": request_id,
        "evidence_id": evidence_id,
        "actor_ref": actor_ref,
    }


def qualify_bank_services(*, r1_path: str, mission_id: str, target_id: str) -> Dict[str, Any]:
    _install_overlays()
    truth = TruthRuntime(Path(r1_path).expanduser().resolve())
    task = _execution_task(truth, mission_id)
    task_id = str(task["task_id"])
    capability_result: Dict[str, Dict[str, Any]] = {}
    blockers: List[str] = []
    for capability in REQUIRED_CAPABILITIES:
        rows = [
            row for row in truth.query("rc7_evidence", mission_id=mission_id)
            if row.get("kind") == PROBE_KIND
            and target_id in list(row.get("subject_refs") or [])
            and capability in list(row.get("subject_refs") or [])
        ]
        if len(rows) != 1:
            capability_result[capability] = {"status": "HOLD", "probe_count": len(rows)}
            blockers.append("BANK_FIELD_SERVICE_PROBE_NOT_UNIQUE:%s:%d" % (capability, len(rows)))
            continue
        row = rows[0]
        source_ref = str(row.get("source_ref") or "")
        if not source_ref.startswith("provider://"):
            capability_result[capability] = {"status": "HOLD", "reason": "PROVIDER_SOURCE_REQUIRED"}
            blockers.append("BANK_FIELD_PROVIDER_SOURCE_REQUIRED:%s" % capability)
            continue
        subjects = list(row.get("subject_refs") or [])
        approval_id = None
        if capability == CAP_DB_WRITE:
            approvals = [
                ref for ref in subjects
                if isinstance(ref, str) and ref.startswith("EVD-HGAPP-")
            ]
            if len(approvals) != 1:
                capability_result[capability] = {"status": "HOLD", "reason": "DB_WRITE_HUMAN_GATE_APPROVAL_REQUIRED"}
                blockers.append("BANK_FIELD_DB_WRITE_HUMAN_GATE_APPROVAL_REQUIRED")
                continue
            approval_id = approvals[0]
            approval_rows = truth.query("rc7_evidence", evidence_id=approval_id)
            if len(approval_rows) != 1 or approval_rows[0].get("kind") != HUMAN_GATE_APPROVAL_KIND:
                capability_result[capability] = {"status": "HOLD", "reason": "DB_WRITE_HUMAN_GATE_APPROVAL_INVALID"}
                blockers.append("BANK_FIELD_DB_WRITE_HUMAN_GATE_APPROVAL_INVALID")
                continue
        capability_result[capability] = {
            "status": "PASS",
            "probe_evidence_id": row.get("evidence_id"),
            "provider_source_ref": source_ref,
            "human_gate_approval_evidence_id": approval_id,
        }

    # Mission applicability is informative unless the Mission actually required
    # CAT and did not query it. Platform Bank Final still requires all four
    # service probes independently of what one selected business case happened
    # to exercise.
    provider_calls = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == PROVIDER_CALL_KIND
    ]
    observed_caps = sorted({
        str(ref)
        for row in provider_calls
        for ref in list(row.get("subject_refs") or [])
        if isinstance(ref, str) and (ref.startswith("PRECONDITION_") or ref.startswith("DATA_"))
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "HOLD",
        "qualification_kind": "BANK_FIELD_PLATFORM_SERVICES_PLUS_MISSION_APPLICABILITY",
        "mission_id": mission_id,
        "task_id": task_id,
        "target_id": target_id,
        "platform_capabilities": capability_result,
        "mission_applicability": {
            "observed_case_provider_capabilities": observed_caps,
            "auth_precondition_used": "PRECONDITION_AUTH" in observed_caps,
            "db_create_used": "DATA_DB_CREATE" in observed_caps,
        },
        "blocking_reasons": blockers,
    }


def _write(path: Optional[str], result: Mapping[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(result), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_runtime.bank_field_services")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe")
    probe.add_argument("--r1", required=True)
    probe.add_argument("--state-root", required=True)
    probe.add_argument("--provider-config", required=True)
    probe.add_argument("--mission-id", required=True)
    probe.add_argument("--target-id", required=True)
    probe.add_argument("--output")
    probe.add_argument("--require-pass", action="store_true")

    approve = sub.add_parser("approve-db-write")
    approve.add_argument("--r1", required=True)
    approve.add_argument("--state-root", required=True)
    approve.add_argument("--mission-id", required=True)
    approve.add_argument("--target-id", required=True)
    approve.add_argument("--request-id", required=True)
    approve.add_argument("--actor-ref", required=True)
    approve.add_argument("--reason", required=True)
    approve.add_argument("--output")

    qualify = sub.add_parser("qualify")
    qualify.add_argument("--r1", required=True)
    qualify.add_argument("--mission-id", required=True)
    qualify.add_argument("--target-id", required=True)
    qualify.add_argument("--output")
    qualify.add_argument("--require-pass", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            result = probe_bank_services(
                r1_path=args.r1,
                state_root=args.state_root,
                provider_config=args.provider_config,
                mission_id=args.mission_id,
                target_id=args.target_id,
            )
            _write(args.output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if args.require_pass and result["status"] != "PASS":
                return 3 if result["status"] == "HUMAN_GATE_REQUIRED" else 2
            return 0
        if args.command == "approve-db-write":
            result = approve_db_write_probe(
                r1_path=args.r1,
                state_root=args.state_root,
                mission_id=args.mission_id,
                target_id=args.target_id,
                request_id=args.request_id,
                actor_ref=args.actor_ref,
                reason=args.reason,
            )
            _write(args.output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "qualify":
            result = qualify_bank_services(
                r1_path=args.r1,
                mission_id=args.mission_id,
                target_id=args.target_id,
            )
            _write(args.output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if args.require_pass and result["status"] != "PASS":
                return 2
            return 0
        raise BankFieldServiceError("BANK_FIELD_SERVICE_COMMAND_REQUIRED")
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
