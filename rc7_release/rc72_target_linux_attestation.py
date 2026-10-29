from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence


OBSERVATION_SCHEMA = "pfc.aitest.rc7.2.target-linux-observation.v1"
REQUEST_SCHEMA = "pfc.aitest.rc7.2.target-linux-attestation-request.v1"
ATTESTATION_SCHEMA = "pfc.aitest.rc7.2.target-linux-attestation.v1"
EVALUATION_SCHEMA = "pfc.aitest.rc7.2.target-linux-attestation-evaluation.v1"
GENERIC_RUNNER_KIND = "GITHUB_HOSTED_GENERIC"
TRUSTED_VERIFIER_KINDS = frozenset(
    {
        "APPROVED_SELF_HOSTED_TARGET_LINUX",
        "BANK_FIELD_TARGET_LINUX",
    }
)
FIELD_VERIFIER_KIND = "BANK_FIELD_TARGET_LINUX"
FIELD_RUNNER_KIND = "BANK_FIELD_TARGET"
_REQUIRED_MACHINE_FIELDS = (
    "platform_family",
    "platform_release",
    "architecture",
    "runner_identity",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _valid_source(value: object) -> Optional[str]:
    text = str(value or "").strip()
    return text.lower() if _SHA_RE.fullmatch(text) else None


def _require_observation(observation: Mapping[str, object]) -> str:
    if not isinstance(observation, Mapping):
        raise ValueError("TARGET_LINUX_OBSERVATION_INVALID")
    source = _valid_source(observation.get("source_commit"))
    if source is None:
        raise ValueError("TARGET_LINUX_OBSERVATION_SOURCE_INVALID")
    if str(observation.get("schema") or "") != OBSERVATION_SCHEMA:
        raise ValueError("TARGET_LINUX_OBSERVATION_SCHEMA_INVALID")
    return source


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def observation_digest(observation: Mapping[str, object]) -> str:
    _require_observation(observation)
    return hashlib.sha256(_canonical_json(observation)).hexdigest()


def build_attestation_request(observation: Mapping[str, object]) -> Dict[str, object]:
    source = _require_observation(observation)
    digest = observation_digest(observation)
    return {
        "schema": REQUEST_SCHEMA,
        "source_commit": source,
        "observation_digest": digest,
        "platform_family": str(observation.get("platform_family") or ""),
        "platform_release": str(observation.get("platform_release") or ""),
        "architecture": str(observation.get("architecture") or ""),
        "python_version": str(observation.get("python_version") or ""),
        "shell": str(observation.get("shell") or ""),
        "runner_kind": str(observation.get("runner_kind") or ""),
        "runner_identity": str(observation.get("runner_identity") or ""),
        "state": "AWAITING_EXTERNAL_ATTESTATION",
        "target_linux_verified": False,
        "field_verified": False,
        "bank_final": False,
    }


class LocalFileAttestationVerifier:
    """Deliberately untrusted adapter for diagnostics and negative controls only."""

    kind = "UNTRUSTED_LOCAL_FILE_ATTESTATION"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def verify(self, ref: str) -> Mapping[str, object]:
        path = Path(ref) if str(ref or "").strip() else self.path
        return json.loads(path.read_text(encoding="utf-8"))


def _base_evaluation(observation: Mapping[str, object]) -> Dict[str, object]:
    source = _require_observation(observation)
    digest = observation_digest(observation)
    return {
        "schema": EVALUATION_SCHEMA,
        "source_commit": source,
        "observation_digest": digest,
        "platform_family": str(observation.get("platform_family") or ""),
        "platform_release": str(observation.get("platform_release") or ""),
        "architecture": str(observation.get("architecture") or ""),
        "python_version": str(observation.get("python_version") or ""),
        "shell": str(observation.get("shell") or ""),
        "runner_kind": str(observation.get("runner_kind") or ""),
        "runner_identity": str(observation.get("runner_identity") or ""),
        "status": "HOLD",
        "reason": None,
        "evidence_refs": [],
        "verifier_kind": None,
        "target_linux_verified": False,
        "field_verified": False,
        "bank_final": False,
        "notes": [],
    }


def _decision(base: Mapping[str, object], status: str, reason: Optional[str], **updates: object) -> Dict[str, object]:
    result = dict(base)
    result.update(updates)
    result["status"] = status
    result["reason"] = reason
    # Q3 can only qualify target Linux. BANK_FINAL remains Q9.
    result["bank_final"] = False
    return result


def evaluate_bound_target_attestation(
    *,
    observation: Mapping[str, object],
    attestation_ref: str,
    verifier: object,
) -> Dict[str, object]:
    base = _base_evaluation(observation)

    if str(observation.get("runner_kind") or "") == GENERIC_RUNNER_KIND:
        return _decision(
            base,
            "HOLD",
            "GENERIC_LINUX_PROXY_NOT_TARGET",
            notes=["Generic hosted Linux is an engineering proxy, never target Linux evidence."],
        )

    if not str(attestation_ref or "").strip() or verifier is None:
        return _decision(base, "HOLD", "TARGET_LINUX_ATTESTATION_REQUIRED")

    verifier_kind = str(getattr(verifier, "kind", "") or "")
    base["verifier_kind"] = verifier_kind
    if verifier_kind not in TRUSTED_VERIFIER_KINDS:
        return _decision(base, "HOLD", "UNTRUSTED_TARGET_LINUX_VERIFIER")

    try:
        attestation = verifier.verify(str(attestation_ref))
    except Exception as exc:
        return _decision(
            base,
            "FAIL",
            "TARGET_LINUX_ATTESTATION_VERIFY_FAILED",
            notes=[str(exc)],
        )
    if not isinstance(attestation, Mapping):
        return _decision(base, "FAIL", "TARGET_LINUX_ATTESTATION_INVALID")
    if str(attestation.get("schema") or "") != ATTESTATION_SCHEMA:
        return _decision(base, "FAIL", "TARGET_LINUX_ATTESTATION_SCHEMA_INVALID")

    observed_source = str(base["source_commit"])
    attested_source = _valid_source(attestation.get("source_commit"))
    if attested_source != observed_source:
        return _decision(base, "FAIL", "TARGET_LINUX_SOURCE_COMMIT_MISMATCH")

    if str(attestation.get("observation_digest") or "").lower() != str(base["observation_digest"]):
        return _decision(base, "FAIL", "TARGET_LINUX_OBSERVATION_DIGEST_MISMATCH")

    for field in _REQUIRED_MACHINE_FIELDS:
        if str(attestation.get(field) or "").strip() != str(observation.get(field) or "").strip():
            return _decision(base, "FAIL", "TARGET_LINUX_ATTESTATION_MACHINE_MISMATCH")

    if str(attestation.get("decision") or "").upper() != "APPROVED":
        return _decision(base, "HOLD", "TARGET_LINUX_ATTESTATION_NOT_APPROVED")
    if attestation.get("target_environment_approved") is not True:
        return _decision(base, "HOLD", "TARGET_LINUX_ENVIRONMENT_NOT_APPROVED")

    evidence_refs = [
        str(item)
        for item in (attestation.get("evidence_refs") or ())
        if str(item).strip()
    ]
    if not evidence_refs:
        return _decision(base, "HOLD", "TARGET_LINUX_EVIDENCE_REQUIRED")

    field_verified = (
        verifier_kind == FIELD_VERIFIER_KIND
        and str(observation.get("runner_kind") or "") == FIELD_RUNNER_KIND
    )
    return _decision(
        base,
        "PASS",
        None,
        evidence_refs=evidence_refs,
        target_linux_verified=True,
        field_verified=field_verified,
        notes=[
            "Target Linux attestation is bound to the exact observation digest and source lineage.",
            "BANK_FINAL remains a later Q9 decision.",
        ],
    )


def _read_json(path: str) -> Mapping[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("TARGET_LINUX_JSON_OBJECT_REQUIRED")
    return payload


def _write_json(path: str, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RC7.2 Q3 external target-Linux attestation boundary")
    sub = parser.add_subparsers(dest="command")

    request = sub.add_parser("request")
    request.add_argument("--observation", required=True)
    request.add_argument("--output", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "request":
        parser.error("command required")

    observation = _read_json(args.observation)
    request = build_attestation_request(observation)
    _write_json(args.output, request)
    print(json.dumps(request, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
