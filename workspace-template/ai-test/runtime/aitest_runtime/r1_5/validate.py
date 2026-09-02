from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .capabilities import discover_capabilities
from .configuration import DeclaredConfiguration, default_configuration, load_configuration
from .contracts import ArtifactProvenance, CapabilityEvidence, R15Error, ValidationCheck, ValidationReport, utc_now
from .install import receipt_path, validate_installed_artifact, verify_distribution


@dataclass(frozen=True)
class ValidatedStartup:
    artifact: ArtifactProvenance
    configuration: DeclaredConfiguration
    capabilities: tuple[CapabilityEvidence, ...]
    report: ValidationReport

    def require_valid(self) -> "ValidatedStartup":
        self.report.require_valid()
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact": self.artifact.to_dict(),
            "configuration": self.configuration.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "validation": self.report.to_dict(),
        }


def _check(check_id: str, ok: bool | None, code: str, message: str, **evidence: object) -> ValidationCheck:
    status = "UNKNOWN" if ok is None else ("PASS" if ok else "FAIL")
    return ValidationCheck(check_id, status, code, message, evidence)


def validate_runtime(
    configuration: DeclaredConfiguration,
    artifact: ArtifactProvenance,
    capabilities: Iterable[CapabilityEvidence] | None = None,
) -> ValidatedStartup:
    records = tuple(capabilities if capabilities is not None else discover_capabilities(configuration))
    checks: list[ValidationCheck] = []
    checks.append(_check("artifact.provenance", len(artifact.manifest_digest) == 64, "ARTIFACT_PROVENANCE", "artifact provenance is verified", source=artifact.source))
    checks.append(
        _check(
            "configuration.provenance",
            configuration.provenance.get("digest") == artifact.manifest_digest,
            "CONFIGURATION_PROVENANCE",
            "configuration provenance matches the verified artifact",
        )
    )
    checks.append(
        _check(
            "identity.artifact",
            configuration.identity.get("artifact_digest") == artifact.manifest_digest,
            "IDENTITY_PROVENANCE",
            "installation identity is anchored to the verified artifact",
        )
    )
    checks.append(
        _check(
            "identity.lineage",
            configuration.identity.get("lineage_policy") == "PRESERVE",
            "LINEAGE_POLICY",
            "R1.1-R1.4 identity and lineage are preserved",
        )
    )
    workspace = Path(str(configuration.runtime["workspace_root"])).resolve()
    db_path = Path(str(configuration.runtime["db_path"])).resolve()
    allowed_roots = tuple(Path(str(item)).resolve() for item in configuration.security["allowed_roots"])
    db_allowed = any(db_path == root or root in db_path.parents for root in allowed_roots)
    workspace_allowed = any(workspace == root or root in workspace.parents for root in allowed_roots)
    checks.append(_check("security.paths", db_allowed and workspace_allowed, "PATH_BOUNDARY", "runtime paths are within declared roots"))
    checks.append(
        _check(
            "security.policy",
            configuration.security.get("network") == "DENY"
            and configuration.security.get("bind_host") in {"127.0.0.1", "::1", "localhost"}
            and configuration.security.get("allow_external_side_effects") is False,
            "SECURITY_POLICY",
            "startup policy is loopback-only and denies external side effects",
        )
    )
    required = {item.capability_id for item in records if item.required}
    declared_required = set(configuration.capabilities["required"])
    checks.append(_check("capabilities.complete", required == declared_required, "CAPABILITY_EVIDENCE_COMPLETE", "all required capabilities have evidence"))
    for item in records:
        if item.required:
            state: bool | None = item.available if item.discovered else None
            checks.append(
                _check(
                    f"capability.{item.capability_id}",
                    state,
                    "CAPABILITY_AVAILABLE",
                    "required capability is discovered, validated, authorized, and available",
                    capability=item.to_dict(),
                )
            )
    report = ValidationReport(
        configuration_digest=configuration.digest,
        artifact_digest=artifact.manifest_digest,
        checks=tuple(checks),
        validated_at=utc_now(),
    )
    return ValidatedStartup(artifact, configuration, records, report)


def _find_package_root(workspace: Path) -> Path | None:
    candidates = (workspace, *workspace.parents)
    for candidate in candidates:
        if (candidate / "PACKAGE_MANIFEST.json").is_file() and (candidate / "workspace-template" / "VERSION").is_file():
            return candidate
    return None


def validate_startup(
    workspace_root: str | Path,
    *,
    package_root: str | Path | None = None,
    configuration_path: str | Path | None = None,
) -> ValidatedStartup:
    workspace = Path(workspace_root).resolve()
    if receipt_path(workspace).is_file():
        artifact, installed_configuration = validate_installed_artifact(workspace)
        configuration = load_configuration(configuration_path) if configuration_path else installed_configuration
    else:
        root = Path(package_root).resolve() if package_root else _find_package_root(workspace)
        if root is None:
            raise R15Error("ARTIFACT_PROVENANCE_UNKNOWN", "no package manifest or installation receipt establishes provenance")
        artifact = verify_distribution(root)
        configuration = load_configuration(configuration_path) if configuration_path else default_configuration(workspace, artifact, source="verified-package-default")
    return validate_runtime(configuration, artifact)
