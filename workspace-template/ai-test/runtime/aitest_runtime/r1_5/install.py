from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .configuration import DeclaredConfiguration, default_configuration
from .contracts import (
    DISTRIBUTION_MANIFEST_SCHEMA_VERSION,
    DISTRIBUTION_VERSION,
    ArtifactProvenance,
    R15Error,
    utc_now,
)


EXCLUDED_DISTRIBUTION_PATHS = frozenset(
    {
        "PACKAGE_MANIFEST.json",
        "verification/PACKAGE_VERIFICATION_REPORT.json",
        "verification/RELEASE_VERIFICATION_REPORT.json",
        "verification/ZIP_EXTRACTION_VERIFICATION.json",
        "verification/ZIP_EXTRACTION_GATE_REPORT.json",
    }
)
INSTALLATION_RECEIPT = ".aitest-r1-5-installation.json"
INSTALLATION_RECEIPT_SCHEMA_VERSION = "1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise R15Error("MANIFEST_PATH_UNSAFE", "manifest contains an unsafe path", {"path": value})
    return value


def _tracked_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        parts = PurePosixPath(rel).parts
        if (
            parts[0] in {".git", ".pytest_cache", "dist"}
            or "__pycache__" in parts
            or path.suffix in {".pyc", ".pyo"}
            or rel in EXCLUDED_DISTRIBUTION_PATHS
            or path.name == ".DS_Store"
        ):
            continue
        result[rel] = path
    return result


def verify_distribution(package_root: str | Path) -> ArtifactProvenance:
    root = Path(package_root).resolve()
    manifest_path = root / "PACKAGE_MANIFEST.json"
    try:
        raw_bytes = manifest_path.read_bytes()
        manifest = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R15Error("DISTRIBUTION_MANIFEST_UNREADABLE", "package manifest could not be read or parsed") from exc
    if not isinstance(manifest, Mapping) or not isinstance(manifest.get("files"), list):
        raise R15Error("MANIFEST_SCHEMA_INVALID", "package manifest must contain a files list")
    if manifest.get("schema_version") != DISTRIBUTION_MANIFEST_SCHEMA_VERSION:
        raise R15Error("MANIFEST_SCHEMA_INCOMPATIBLE", "unsupported package manifest schema")
    if manifest.get("version") != DISTRIBUTION_VERSION:
        raise R15Error("DISTRIBUTION_VERSION_INCOMPATIBLE", "unsupported distribution version")
    version_path = root / "workspace-template" / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise R15Error("DISTRIBUTION_VERSION_MISSING", "workspace version declaration is missing") from exc
    if version != manifest.get("version"):
        raise R15Error("DISTRIBUTION_VERSION_CONFLICT", "workspace and manifest versions disagree")

    expected: dict[str, Mapping[str, Any]] = {}
    for record in manifest["files"]:
        if not isinstance(record, Mapping):
            raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest file records must be objects")
        rel = _safe_relative(record.get("path"))
        if rel in expected:
            raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest contains a duplicate path", {"path": rel})
        size, digest = record.get("size"), record.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest file size must be a non-negative integer", {"path": rel})
        if not isinstance(digest, str) or len(digest) != 64:
            raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest file digest must be SHA-256", {"path": rel})
        expected[rel] = {"size": size, "sha256": digest.lower()}
    if manifest.get("file_count") != len(expected):
        raise R15Error("MANIFEST_SCHEMA_INVALID", "manifest file_count is inconsistent")

    actual = _tracked_files(root)
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    if missing or extra:
        raise R15Error("DISTRIBUTION_FILE_SET_MISMATCH", "distribution file set does not match the manifest", {"missing": missing, "extra": extra})
    mismatches = []
    for rel in sorted(expected):
        path = actual[rel]
        size, digest = path.stat().st_size, _sha256(path)
        if size != expected[rel]["size"] or digest != expected[rel]["sha256"]:
            mismatches.append(rel)
    if mismatches:
        raise R15Error("DISTRIBUTION_INTEGRITY_FAILED", "one or more distribution files failed integrity validation", {"paths": mismatches})
    records = {rel: {"size": expected[rel]["size"], "sha256": expected[rel]["sha256"]} for rel in sorted(expected)}
    return ArtifactProvenance(
        root=root,
        source=str(manifest_path),
        distribution_version=str(manifest["version"]),
        manifest_schema_version=str(manifest["schema_version"]),
        manifest_digest=hashlib.sha256(raw_bytes).hexdigest(),
        files_digest=canonical_sha256(records),
        file_count=len(records),
        verified_at=utc_now(),
        files=records,
    )


def _validate_prerequisites() -> None:
    if sys.version_info < (3, 10):
        raise R15Error("PYTHON_VERSION_UNSUPPORTED", "Python 3.10 or newer is required")
    if not hasattr(os, "replace"):
        raise R15Error("FILESYSTEM_PREREQUISITE_MISSING", "atomic file replacement is unavailable")


def receipt_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).resolve() / INSTALLATION_RECEIPT


@dataclass(frozen=True)
class InstallationResult:
    outcome: str
    workspace_root: Path
    artifact: ArtifactProvenance
    configuration: DeclaredConfiguration
    receipt: Path

    @property
    def ok(self) -> bool:
        return self.outcome in {"INSTALLED", "DUPLICATE"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "workspace_root": str(self.workspace_root),
            "artifact": self.artifact.to_dict(),
            "configuration": self.configuration.to_dict(),
            "receipt": str(self.receipt),
        }


def _receipt_document(artifact: ArtifactProvenance, configuration: DeclaredConfiguration) -> dict[str, Any]:
    prefix = "workspace-template/"
    workspace_files = {
        rel[len(prefix):]: dict(record)
        for rel, record in artifact.files.items()
        if rel.startswith(prefix)
    }
    return {
        "schema_version": INSTALLATION_RECEIPT_SCHEMA_VERSION,
        "artifact": artifact.to_dict(),
        "configuration": configuration.to_dict(),
        "workspace_files": workspace_files,
    }


def install_workspace(package_root: str | Path, destination: str | Path) -> InstallationResult:
    artifact = verify_distribution(package_root)
    _validate_prerequisites()
    source = artifact.root / "workspace-template"
    target = Path(destination).resolve()
    target_receipt = receipt_path(target)
    configuration = default_configuration(target, artifact, source="installation-receipt")
    if target.exists() and any(target.iterdir()):
        if not target_receipt.is_file():
            raise R15Error("INSTALL_DESTINATION_CONFLICT", "destination exists without an R1.5 installation receipt", {"destination": str(target)})
        installed_artifact, installed_configuration = validate_installed_artifact(target)
        if installed_artifact.manifest_digest != artifact.manifest_digest:
            raise R15Error("INSTALL_ARTIFACT_CONFLICT", "destination was installed from a different artifact")
        return InstallationResult("DUPLICATE", target, installed_artifact, installed_configuration, target_receipt)
    if target.exists() and not target.is_dir():
        raise R15Error("INSTALL_DESTINATION_CONFLICT", "destination is not a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    created = not target.exists()
    try:
        if created:
            shutil.copytree(source, target)
        else:
            shutil.copytree(source, target, dirs_exist_ok=True)
        document = _receipt_document(artifact, configuration)
        temporary = target / f"{INSTALLATION_RECEIPT}.tmp"
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target_receipt)
    except Exception:
        if created and target.exists():
            shutil.rmtree(target)
        raise
    return InstallationResult("INSTALLED", target, artifact, configuration, target_receipt)


def validate_installed_artifact(workspace_root: str | Path) -> tuple[ArtifactProvenance, DeclaredConfiguration]:
    workspace = Path(workspace_root).resolve()
    path = receipt_path(workspace)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R15Error("INSTALLATION_RECEIPT_UNREADABLE", "installation receipt could not be read or parsed") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != INSTALLATION_RECEIPT_SCHEMA_VERSION:
        raise R15Error("INSTALLATION_RECEIPT_INCOMPATIBLE", "unsupported installation receipt")
    raw_artifact = document.get("artifact")
    records = document.get("workspace_files")
    if not isinstance(raw_artifact, Mapping) or not isinstance(records, Mapping):
        raise R15Error("INSTALLATION_RECEIPT_INVALID", "installation receipt provenance is incomplete")
    mismatches = []
    for rel, record in records.items():
        safe_rel = _safe_relative(rel)
        if not isinstance(record, Mapping):
            raise R15Error("INSTALLATION_RECEIPT_INVALID", "workspace file record is invalid")
        file_path = workspace / safe_rel
        if not file_path.is_file() or file_path.is_symlink():
            mismatches.append(safe_rel)
            continue
        if file_path.stat().st_size != record.get("size") or _sha256(file_path) != record.get("sha256"):
            mismatches.append(safe_rel)
    if mismatches:
        raise R15Error("INSTALLED_ARTIFACT_INTEGRITY_FAILED", "installed runtime files failed integrity validation", {"paths": sorted(mismatches)})
    artifact = ArtifactProvenance(
        root=workspace,
        source=str(path),
        distribution_version=str(raw_artifact.get("distribution_version")),
        manifest_schema_version=str(raw_artifact.get("manifest_schema_version")),
        manifest_digest=str(raw_artifact.get("manifest_digest")),
        files_digest=str(raw_artifact.get("files_digest")),
        file_count=int(raw_artifact.get("file_count", 0)),
        verified_at=utc_now(),
        files={str(key): dict(value) for key, value in records.items() if isinstance(value, Mapping)},
    )
    raw_configuration = document.get("configuration")
    if not isinstance(raw_configuration, Mapping):
        raise R15Error("INSTALLATION_RECEIPT_INVALID", "installation configuration is missing")
    configuration = DeclaredConfiguration.from_mapping(raw_configuration)
    if Path(str(configuration.runtime["workspace_root"])).resolve() != workspace:
        raise R15Error("INSTALLATION_IDENTITY_MISMATCH", "installation receipt belongs to a different workspace")
    if configuration.identity["artifact_digest"] != artifact.manifest_digest:
        raise R15Error("INSTALLATION_PROVENANCE_MISMATCH", "configuration and artifact provenance disagree")
    return artifact, configuration
