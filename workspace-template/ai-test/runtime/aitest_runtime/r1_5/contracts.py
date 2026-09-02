from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_json, canonical_sha256


R1_5_CONTRACT_VERSION = "1.0"
DISTRIBUTION_VERSION = "1.11.1"
DISTRIBUTION_MANIFEST_SCHEMA_VERSION = "1.0"
RUNTIME_VERSION = "1"
CONFIGURATION_SCHEMA_VERSION = "1.0"
COMMAND_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
PROJECTION_SCHEMA_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.0"

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "passwd",
        "password",
        "pwd",
        "secret",
        "secret_ref",
        "token",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def contains_sensitive_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS and item not in (None, "", "<redacted>"):
                return True
            if contains_sensitive_value(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(contains_sensitive_value(item) for item in value)
    return False


class R15Error(Exception):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("error code must be a non-empty string")
        self.code = code
        self.message = str(message)
        self.details = redact(dict(details or {}))
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


@dataclass(frozen=True)
class VersionContract:
    distribution: str = DISTRIBUTION_VERSION
    runtime: str = RUNTIME_VERSION
    configuration_schema: str = CONFIGURATION_SCHEMA_VERSION
    command_schema: int = COMMAND_SCHEMA_VERSION
    event_schema: int = EVENT_SCHEMA_VERSION
    projection_schema: str = PROJECTION_SCHEMA_VERSION
    report_schema: str = REPORT_SCHEMA_VERSION
    r1_5_contract: str = R1_5_CONTRACT_VERSION

    def __post_init__(self) -> None:
        expected = VersionContract.supported().to_dict() if self != VersionContract.supported() else self.to_dict()
        actual = self.to_dict()
        if actual != expected:
            mismatches = {key: {"expected": expected[key], "actual": actual[key]} for key in expected if actual[key] != expected[key]}
            raise R15Error("VERSION_INCOMPATIBLE", "one or more declared versions are unsupported", mismatches)

    @classmethod
    def supported(cls) -> "VersionContract":
        value = object.__new__(cls)
        object.__setattr__(value, "distribution", DISTRIBUTION_VERSION)
        object.__setattr__(value, "runtime", RUNTIME_VERSION)
        object.__setattr__(value, "configuration_schema", CONFIGURATION_SCHEMA_VERSION)
        object.__setattr__(value, "command_schema", COMMAND_SCHEMA_VERSION)
        object.__setattr__(value, "event_schema", EVENT_SCHEMA_VERSION)
        object.__setattr__(value, "projection_schema", PROJECTION_SCHEMA_VERSION)
        object.__setattr__(value, "report_schema", REPORT_SCHEMA_VERSION)
        object.__setattr__(value, "r1_5_contract", R1_5_CONTRACT_VERSION)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VersionContract":
        expected = set(cls.supported().to_dict())
        if set(value) != expected:
            raise R15Error(
                "VERSION_CONTRACT_INVALID",
                "version contract fields must exactly match the supported schema",
                {"missing": sorted(expected - set(value)), "unknown": sorted(set(value) - expected)},
            )
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution": self.distribution,
            "runtime": self.runtime,
            "configuration_schema": self.configuration_schema,
            "command_schema": self.command_schema,
            "event_schema": self.event_schema,
            "projection_schema": self.projection_schema,
            "report_schema": self.report_schema,
            "r1_5_contract": self.r1_5_contract,
        }


@dataclass(frozen=True)
class ArtifactProvenance:
    root: Path
    source: str
    distribution_version: str
    manifest_schema_version: str
    manifest_digest: str
    files_digest: str
    file_count: int
    verified_at: str
    files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.distribution_version != DISTRIBUTION_VERSION:
            raise R15Error("DISTRIBUTION_VERSION_INCOMPATIBLE", "unsupported distribution version")
        if self.manifest_schema_version != DISTRIBUTION_MANIFEST_SCHEMA_VERSION:
            raise R15Error("MANIFEST_SCHEMA_INCOMPATIBLE", "unsupported package manifest schema")
        for name, digest in (("manifest_digest", self.manifest_digest), ("files_digest", self.files_digest)):
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
                raise R15Error("PROVENANCE_INVALID", f"{name} must be a SHA-256 digest")

    def to_dict(self, *, include_files: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "root": str(self.root),
            "source": self.source,
            "distribution_version": self.distribution_version,
            "manifest_schema_version": self.manifest_schema_version,
            "manifest_digest": self.manifest_digest,
            "files_digest": self.files_digest,
            "file_count": self.file_count,
            "verified_at": self.verified_at,
        }
        if include_files:
            result["files"] = {key: dict(self.files[key]) for key in sorted(self.files)}
        return result


@dataclass(frozen=True)
class CapabilityEvidence:
    capability_id: str
    discovered: bool
    required: bool
    validated: bool
    authorized: bool
    available: bool
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "discovered": self.discovered,
            "required": self.required,
            "validated": self.validated,
            "authorized": self.authorized,
            "available": self.available,
            "evidence": redact(dict(self.evidence)),
        }


@dataclass(frozen=True)
class ValidationCheck:
    check_id: str
    status: str
    code: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("validation status must be PASS, FAIL, or UNKNOWN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "evidence": redact(dict(self.evidence)),
        }


@dataclass(frozen=True)
class ValidationReport:
    configuration_digest: str
    artifact_digest: str
    checks: tuple[ValidationCheck, ...]
    validated_at: str
    contract_version: str = R1_5_CONTRACT_VERSION
    report_schema_version: str = REPORT_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return bool(self.checks) and all(check.status == "PASS" for check in self.checks)

    @property
    def status(self) -> str:
        return "VALID" if self.valid else "INVALID"

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict(include_digest=False))

    def require_valid(self) -> None:
        if not self.valid:
            raise R15Error(
                "STARTUP_VALIDATION_FAILED",
                "runtime launch requires a fully valid startup report",
                {"failed_checks": [item.check_id for item in self.checks if item.status != "PASS"]},
            )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "report_schema_version": self.report_schema_version,
            "contract_version": self.contract_version,
            "status": self.status,
            "configuration_digest": self.configuration_digest,
            "artifact_digest": self.artifact_digest,
            "validated_at": self.validated_at,
            "checks": [item.to_dict() for item in self.checks],
        }
        if include_digest:
            result["digest"] = canonical_sha256(result)
        return result


@dataclass(frozen=True)
class LaunchReceipt:
    launch_id: str
    runtime_id: str
    runtime_db_path: str
    artifact_digest: str
    configuration_digest: str
    validation_digest: str
    launched_at: str
    versions: VersionContract

    def to_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "runtime_id": self.runtime_id,
            "runtime_db_path": self.runtime_db_path,
            "artifact_digest": self.artifact_digest,
            "configuration_digest": self.configuration_digest,
            "validation_digest": self.validation_digest,
            "launched_at": self.launched_at,
            "versions": self.versions.to_dict(),
        }


def stable_digest(value: Mapping[str, Any]) -> str:
    canonical_json(value)
    return canonical_sha256(value)
