from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import (
    CONFIGURATION_SCHEMA_VERSION,
    ArtifactProvenance,
    R15Error,
    VersionContract,
    contains_sensitive_value,
)


_FIELDS = {
    "schema_version",
    "source",
    "precedence",
    "versions",
    "runtime",
    "capabilities",
    "security",
    "identity",
    "provenance",
    "digest",
}


def _mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R15Error("CONFIGURATION_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _strings(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise R15Error("CONFIGURATION_SCHEMA_INVALID", f"{name} must be a list of non-empty strings")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise R15Error("CONFIGURATION_CONFLICT", f"{name} contains duplicates")
    return result


@dataclass(frozen=True)
class DeclaredConfiguration:
    schema_version: str
    source: str
    precedence: tuple[str, ...]
    versions: VersionContract
    runtime: Mapping[str, Any]
    capabilities: Mapping[str, Any]
    security: Mapping[str, Any]
    identity: Mapping[str, Any]
    provenance: Mapping[str, Any]
    digest: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeclaredConfiguration":
        raw = dict(value)
        unknown = set(raw) - _FIELDS
        missing = (_FIELDS - {"digest"}) - set(raw)
        if unknown or missing:
            raise R15Error(
                "CONFIGURATION_SCHEMA_INVALID",
                "configuration fields do not match the R1.5 schema",
                {"unknown": sorted(unknown), "missing": sorted(missing)},
            )
        if raw.get("schema_version") != CONFIGURATION_SCHEMA_VERSION:
            raise R15Error("CONFIGURATION_VERSION_INCOMPATIBLE", "unsupported configuration schema version")
        source = raw.get("source")
        if not isinstance(source, str) or not source.strip():
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "configuration source is required")
        precedence = _strings("precedence", raw.get("precedence"))
        if source not in precedence:
            raise R15Error("CONFIGURATION_PRECEDENCE_INVALID", "source must be declared in precedence")
        versions = VersionContract.from_mapping(_mapping("versions", raw.get("versions")))
        runtime = _mapping("runtime", raw.get("runtime"))
        capabilities = _mapping("capabilities", raw.get("capabilities"))
        security = _mapping("security", raw.get("security"))
        identity = _mapping("identity", raw.get("identity"))
        provenance = _mapping("provenance", raw.get("provenance"))
        cls._validate_runtime(runtime)
        cls._validate_capabilities(capabilities)
        cls._validate_security(security)
        cls._validate_identity(identity)
        cls._validate_provenance(provenance)
        if contains_sensitive_value(raw):
            raise R15Error("INLINE_SECRET_FORBIDDEN", "configuration may contain references but not secret values")
        unsigned = {key: raw[key] for key in raw if key != "digest"}
        computed = canonical_sha256(unsigned)
        declared = raw.get("digest")
        if declared is not None and declared != computed:
            raise R15Error("CONFIGURATION_DIGEST_MISMATCH", "declared configuration digest does not match content")
        return cls(
            CONFIGURATION_SCHEMA_VERSION,
            source,
            precedence,
            versions,
            runtime,
            capabilities,
            security,
            identity,
            provenance,
            computed,
        )

    @staticmethod
    def _validate_runtime(value: Mapping[str, Any]) -> None:
        allowed = {"workspace_root", "db_path", "runtime_id"}
        if set(value) != allowed or any(not isinstance(value.get(key), str) or not str(value[key]).strip() for key in allowed):
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "runtime must declare workspace_root, db_path, and runtime_id")

    @staticmethod
    def _validate_capabilities(value: Mapping[str, Any]) -> None:
        if set(value) != {"required", "authorized"}:
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "capabilities must declare required and authorized lists")
        required = _strings("capabilities.required", value.get("required"))
        authorized = _strings("capabilities.authorized", value.get("authorized"))
        if not set(required) <= set(authorized):
            raise R15Error("CAPABILITY_NOT_AUTHORIZED", "every required capability must be explicitly authorized")

    @staticmethod
    def _validate_security(value: Mapping[str, Any]) -> None:
        expected = {"network", "bind_host", "allowed_roots", "allow_external_side_effects"}
        if set(value) != expected:
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "security policy fields are missing or unknown")
        if value.get("network") != "DENY":
            raise R15Error("SECURITY_POLICY_UNSAFE", "R1.5 startup requires network DENY")
        if value.get("bind_host") not in {"127.0.0.1", "::1", "localhost"}:
            raise R15Error("SECURITY_POLICY_UNSAFE", "Control Plane bind host must be loopback")
        if value.get("allow_external_side_effects") is not False:
            raise R15Error("SECURITY_POLICY_UNSAFE", "external side effects must be disabled at startup")
        _strings("security.allowed_roots", value.get("allowed_roots"))

    @staticmethod
    def _validate_identity(value: Mapping[str, Any]) -> None:
        expected = {"installation_id", "artifact_digest", "lineage_policy"}
        if set(value) != expected:
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "identity fields are missing or unknown")
        if value.get("lineage_policy") != "PRESERVE":
            raise R15Error("LINEAGE_POLICY_INVALID", "R1.1-R1.4 lineage must be preserved")
        if any(not isinstance(value.get(key), str) or not str(value[key]).strip() for key in expected):
            raise R15Error("CONFIGURATION_SCHEMA_INVALID", "identity values must be non-empty strings")

    @staticmethod
    def _validate_provenance(value: Mapping[str, Any]) -> None:
        expected = {"kind", "source", "digest"}
        if set(value) != expected or any(not isinstance(value.get(key), str) or not str(value[key]).strip() for key in expected):
            raise R15Error("CONFIGURATION_PROVENANCE_INVALID", "configuration provenance must be complete")

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "source": self.source,
            "precedence": list(self.precedence),
            "versions": self.versions.to_dict(),
            "runtime": dict(self.runtime),
            "capabilities": {
                "required": list(self.capabilities["required"]),
                "authorized": list(self.capabilities["authorized"]),
            },
            "security": {
                **dict(self.security),
                "allowed_roots": list(self.security["allowed_roots"]),
            },
            "identity": dict(self.identity),
            "provenance": dict(self.provenance),
        }
        if include_digest:
            result["digest"] = self.digest
        return result


FOUNDATION_CAPABILITIES = (
    "python",
    "sqlite",
    "filesystem",
    "durable-runtime",
    "command-bus",
    "event-stream",
    "event-store",
    "mission-sequence",
    "r1_2_work_graph",
    "r1_3b_execution_resume",
    "r1_3c_provider_binding",
    "r1_3d_opencode_bridge",
    "r1_4_tool_execution",
)


def default_configuration(workspace_root: str | Path, artifact: ArtifactProvenance, *, source: str) -> DeclaredConfiguration:
    workspace = Path(workspace_root).resolve()
    runtime_id = canonical_sha256({"artifact": artifact.manifest_digest, "workspace": str(workspace)})[:24]
    raw = {
        "schema_version": CONFIGURATION_SCHEMA_VERSION,
        "source": source,
        "precedence": [source],
        "versions": VersionContract.supported().to_dict(),
        "runtime": {
            "workspace_root": str(workspace),
            "db_path": str(workspace / "ai-test" / "state" / "runtime-spine.db"),
            "runtime_id": runtime_id,
        },
        "capabilities": {
            "required": list(FOUNDATION_CAPABILITIES),
            "authorized": list(FOUNDATION_CAPABILITIES),
        },
        "security": {
            "network": "DENY",
            "bind_host": "127.0.0.1",
            "allowed_roots": [str(workspace)],
            "allow_external_side_effects": False,
        },
        "identity": {
            "installation_id": runtime_id,
            "artifact_digest": artifact.manifest_digest,
            "lineage_policy": "PRESERVE",
        },
        "provenance": {
            "kind": "DISTRIBUTION_MANIFEST",
            "source": artifact.source,
            "digest": artifact.manifest_digest,
        },
    }
    return DeclaredConfiguration.from_mapping(raw)


def load_configuration(path: str | Path) -> DeclaredConfiguration:
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R15Error("CONFIGURATION_UNREADABLE", "configuration could not be read or parsed", {"path": str(source)}) from exc
    if not isinstance(value, Mapping):
        raise R15Error("CONFIGURATION_SCHEMA_INVALID", "configuration root must be an object")
    return DeclaredConfiguration.from_mapping(value)
