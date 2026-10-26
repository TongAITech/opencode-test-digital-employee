"""RC8 executable-bundle authority shared by Center validation and Node materialization.

An ExecutableSpec may eventually point at this artifact, but the artifact itself
is not a PASS claim. It is an immutable, hash-verified Maven/JUnit project bundle
that can be materialized without trusting a Worker-chosen local project path.
"""
from __future__ import annotations

import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from rc8_runtime import ArtifactAvailability


EXECUTABLE_BUNDLE_KIND = "MAVEN_JUNIT_EXECUTABLE_BUNDLE"
EXECUTABLE_BUNDLE_FORMAT = "zip-v1"
MAX_BUNDLE_ENTRIES = 10000
MAX_BUNDLE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class ExecutableBundleError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutableBundleAuthority:
    artifact_id: str
    artifact_ref: str
    sha256: str
    size_bytes: int
    project_subdir: str
    file_name: str


def artifact_id_from_ref(value: str) -> str:
    ref = str(value or "").strip()
    if not ref.startswith("artifact:"):
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_ARTIFACT_REF_REQUIRED")
    artifact_id = ref.split(":", 1)[1].strip()
    if not artifact_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_ARTIFACT_REF_REQUIRED")
    return artifact_id


def _safe_project_subdir(value: object) -> str:
    raw = str(value or ".").strip().replace("\\", "/")
    if raw in {"", "."}:
        return "."
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_PROJECT_SUBDIR_UNSAFE")
    return str(path)


def _safe_member_name(value: str) -> str:
    raw = str(value or "")
    if not raw or "\\" in raw:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_MEMBER_UNSAFE")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_MEMBER_UNSAFE")
    normalized = str(path)
    if normalized in {"", "."}:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_MEMBER_UNSAFE")
    return normalized


def _validate_zip(path: Path, project_subdir: str) -> None:
    try:
        archive = zipfile.ZipFile(str(path), "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_ZIP_INVALID") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_BUNDLE_ENTRIES:
            raise ExecutableBundleError("EXECUTABLE_BUNDLE_ENTRY_COUNT_INVALID")
        total = 0
        names = set()
        for info in infos:
            name = _safe_member_name(info.filename)
            if name in names:
                raise ExecutableBundleError("EXECUTABLE_BUNDLE_DUPLICATE_MEMBER")
            names.add(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ExecutableBundleError("EXECUTABLE_BUNDLE_SYMLINK_FORBIDDEN")
            if info.flag_bits & 0x1:
                raise ExecutableBundleError("EXECUTABLE_BUNDLE_ENCRYPTED_MEMBER_FORBIDDEN")
            total += int(info.file_size)
            if total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
                raise ExecutableBundleError("EXECUTABLE_BUNDLE_UNCOMPRESSED_SIZE_EXCEEDED")
        pom_name = "pom.xml" if project_subdir == "." else "%s/pom.xml" % project_subdir
        if pom_name not in names:
            raise ExecutableBundleError("EXECUTABLE_BUNDLE_POM_REQUIRED")


def validate_executable_bundle(
    store: object,
    artifact_ref: str,
    *,
    test_run_id: Optional[str] = None,
    work_item_id: Optional[str] = None,
    node_id: Optional[str] = None,
    case_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
) -> ExecutableBundleAuthority:
    artifact_id = artifact_id_from_ref(artifact_ref)
    manifest = store.repository.get(artifact_id)
    if manifest is None:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_NOT_FOUND")
    if manifest.availability != ArtifactAvailability.AVAILABLE:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_NOT_AVAILABLE")
    if manifest.kind != EXECUTABLE_BUNDLE_KIND:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_KIND_INVALID")
    if test_run_id is not None and manifest.test_run_id != test_run_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_TEST_RUN_MISMATCH")
    if work_item_id is not None and manifest.work_item_id != work_item_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_WORK_ITEM_MISMATCH")
    if node_id is not None and manifest.node_id != node_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_NODE_MISMATCH")
    if case_id is not None and manifest.case_id != case_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_CASE_MISMATCH")
    if attempt_id is not None and manifest.attempt_id != attempt_id:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_ATTEMPT_MISMATCH")
    if str(manifest.metadata.get("bundle_format") or "") != EXECUTABLE_BUNDLE_FORMAT:
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_FORMAT_INVALID")
    if str(manifest.metadata.get("execution_driver") or "") != "maven-junit":
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_DRIVER_INVALID")
    project_subdir = _safe_project_subdir(manifest.metadata.get("project_subdir", "."))
    path = Path(store.content_path(artifact_id))
    _validate_zip(path, project_subdir)
    return ExecutableBundleAuthority(
        artifact_id=artifact_id,
        artifact_ref="artifact:%s" % artifact_id,
        sha256=manifest.sha256.lower(),
        size_bytes=manifest.size_bytes,
        project_subdir=project_subdir,
        file_name=manifest.file_name,
    )


def materialize_executable_bundle(
    bundle_path: str,
    destination_root: str,
    *,
    expected_sha256: str,
    project_subdir: str = ".",
) -> Path:
    """Safely extract an already downloaded bundle into a fresh Attempt workspace."""
    import hashlib

    source = Path(bundle_path)
    if not source.is_file():
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_FILE_NOT_FOUND")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if digest.hexdigest().lower() != str(expected_sha256 or "").strip().lower():
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_HASH_MISMATCH")

    subdir = _safe_project_subdir(project_subdir)
    _validate_zip(source, subdir)
    destination = Path(destination_root)
    if destination.exists():
        if any(destination.iterdir()):
            raise ExecutableBundleError("EXECUTABLE_BUNDLE_DESTINATION_NOT_EMPTY")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()

    try:
        with zipfile.ZipFile(str(source), "r") as archive:
            for info in archive.infolist():
                name = _safe_member_name(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ExecutableBundleError("EXECUTABLE_BUNDLE_SYMLINK_FORBIDDEN")
                target = (destination / Path(*PurePosixPath(name).parts)).resolve()
                if target != root and root not in target.parents:
                    raise ExecutableBundleError("EXECUTABLE_BUNDLE_MEMBER_UNSAFE")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle, target.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    except ExecutableBundleError:
        shutil.rmtree(str(destination), ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(str(destination), ignore_errors=True)
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_EXTRACTION_FAILED") from exc

    project_dir = destination if subdir == "." else destination / Path(*PurePosixPath(subdir).parts)
    if not (project_dir / "pom.xml").is_file():
        shutil.rmtree(str(destination), ignore_errors=True)
        raise ExecutableBundleError("EXECUTABLE_BUNDLE_POM_REQUIRED")
    return project_dir
