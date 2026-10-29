from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence


SCHEMA = "pfc.aitest.rc7.2.target-linux-reality.v1"
QUALIFICATION_KIND = "Q3_TARGET_LINUX"
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


def _source_commit(value: object) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if _SHA_RE.fullmatch(text) else None


def _base_record(source_commit: str, observation: Mapping[str, object]) -> Dict[str, object]:
    return {
        "schema": SCHEMA,
        "qualification_id": "Q3-TARGET-LINUX-%s" % source_commit[:12],
        "qualification_kind": QUALIFICATION_KIND,
        "source_commit": source_commit,
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
        "target_linux_verified": False,
        "field_verified": False,
        "bank_final": False,
        "verifier_kind": None,
        "notes": [],
    }


def _decision(base: Mapping[str, object], status: str, reason: Optional[str], **updates: object) -> Dict[str, object]:
    result = dict(base)
    result.update(updates)
    result["status"] = status
    result["reason"] = reason
    # No Q3 path may ever promote BANK_FINAL.
    result["bank_final"] = False
    return result


def evaluate_target_linux_reality(
    *,
    source_commit: str,
    observation: Mapping[str, object],
    attestation_ref: Optional[str],
    verifier: Optional[object],
) -> Dict[str, object]:
    """Evaluate whether one observed Linux host is an approved RC7.2 target.

    Machine observation is necessary but never sufficient. PASS requires exact
    source lineage, complete observed identity and an attestation from an
    explicitly trusted target verifier. Generic GitHub-hosted Linux is a
    negative-control engineering proxy and is always HOLD.
    """

    commit = _source_commit(source_commit)
    if commit is None:
        base = _base_record("0" * 40, observation)
        return _decision(base, "FAIL", "TARGET_LINUX_SOURCE_COMMIT_INVALID")

    base = _base_record(commit, observation)
    observed_commit = _source_commit(observation.get("source_commit"))
    if observed_commit is None or observed_commit != commit:
        return _decision(base, "FAIL", "TARGET_LINUX_OBSERVATION_SOURCE_MISMATCH")

    if any(not str(observation.get(field) or "").strip() for field in _REQUIRED_MACHINE_FIELDS):
        return _decision(base, "HOLD", "TARGET_LINUX_PLATFORM_IDENTITY_INCOMPLETE")

    # This branch is deliberately before attestation checks: generic hosted
    # Linux can never be upgraded into target truth by a synthetic verifier.
    if str(observation.get("runner_kind") or "") == GENERIC_RUNNER_KIND:
        return _decision(
            base,
            "HOLD",
            "GENERIC_LINUX_PROXY_NOT_TARGET",
            evidence_refs=["probe://os-release", "probe://uname"],
            notes=["Generic Ubuntu/Linux engineering proxy is not target 信创 Linux evidence."],
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

    attested_commit = _source_commit(attestation.get("source_commit"))
    if attested_commit != commit:
        return _decision(base, "FAIL", "TARGET_LINUX_SOURCE_COMMIT_MISMATCH")

    for field in _REQUIRED_MACHINE_FIELDS:
        observed = str(observation.get(field) or "").strip()
        attested = str(attestation.get(field) or "").strip()
        if attested != observed:
            return _decision(base, "FAIL", "TARGET_LINUX_ATTESTATION_MACHINE_MISMATCH")

    if str(attestation.get("decision") or "").upper() != "APPROVED":
        return _decision(base, "HOLD", "TARGET_LINUX_ATTESTATION_NOT_APPROVED")
    if attestation.get("target_environment_approved") is not True:
        return _decision(base, "HOLD", "TARGET_LINUX_ENVIRONMENT_NOT_APPROVED")

    evidence_refs = [str(item) for item in (attestation.get("evidence_refs") or ()) if str(item).strip()]
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
            "Target Linux identity is attested for this exact source lineage.",
            "BANK_FINAL remains a later Q9 decision.",
        ],
    )


def _os_release() -> Dict[str, str]:
    path = Path("/etc/os-release")
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def observe_host(*, source_commit: str, runner_kind: str, runner_identity: str) -> Dict[str, object]:
    release = _os_release()
    family = release.get("NAME") or release.get("ID") or platform.system()
    version = release.get("VERSION_ID") or release.get("VERSION") or platform.release()
    return {
        "source_commit": source_commit,
        "platform_family": family,
        "platform_release": version,
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "shell": os.environ.get("SHELL") or "/bin/bash",
        "runner_kind": runner_kind,
        "runner_identity": runner_identity,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RC7.2 Q3 target Linux reality gate")
    sub = parser.add_subparsers(dest="command")
    probe = sub.add_parser("probe")
    probe.add_argument("--source-commit", required=True)
    probe.add_argument("--runner-kind", required=True)
    probe.add_argument("--runner-identity", required=True)
    probe.add_argument("--output")
    probe.add_argument("--require-hold", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "probe":
        parser.error("command required")

    commit = _source_commit(args.source_commit)
    observation = observe_host(
        source_commit=args.source_commit,
        runner_kind=args.runner_kind,
        runner_identity=args.runner_identity,
    )
    result = evaluate_target_linux_reality(
        source_commit=args.source_commit,
        observation=observation,
        attestation_ref=None,
        verifier=None,
    )
    # Generic negative-control probe is still useful evidence even without a
    # target attestation; keep the exact host observation in notes.
    result["notes"] = list(result.get("notes") or ()) + [
        "observed_host=%s" % json.dumps(observation, ensure_ascii=False, sort_keys=True)
    ]
    result["started_at"] = None
    result["completed_at"] = None

    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    if args.require_hold:
        return 0 if result.get("status") == "HOLD" else 2
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
