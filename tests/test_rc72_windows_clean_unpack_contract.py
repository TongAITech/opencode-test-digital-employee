from __future__ import annotations

from pathlib import Path

import pytest

from rc7_release import package as rc7_package
from rc7_release.rc72_package import (
    BUILD_STATUS,
    RC72_ARCHITECTURE,
    RC72_BUILD_ID_PREFIX,
    RC72_MANIFEST_SCHEMA,
    RC72_PACKAGE_NAME,
    RC72_RELEASE_FAMILY,
    discover_required_rc72_runtime_files,
    promote_manifest_to_rc72,
    validate_rc72_manifest,
)


SOURCE_COMMIT = "a" * 40


def _base_manifest() -> dict:
    return {
        "schema_version": rc7_package.MANIFEST_SCHEMA,
        "status": rc7_package.BUILD_STATUS,
        "source_commit": SOURCE_COMMIT,
        "build_id": "RC7-%s" % SOURCE_COMMIT[:12],
        "architecture": "RC6_CAPABILITY_BASE_DSH_EXECUTION_RC7_CONTROL_PLANE",
        "real_mission_pass": False,
        "delivery_pass": False,
        "bank_field_pass": False,
        "files": [],
    }


def test_rc72_identity_is_distinct_and_never_bank_final() -> None:
    assert RC72_PACKAGE_NAME == "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10"
    assert RC72_MANIFEST_SCHEMA == "pfc.aitest.rc7.2.package.v1"
    assert RC72_BUILD_ID_PREFIX == "RC7.2-"
    assert RC72_RELEASE_FAMILY == "RC7.2"
    assert RC72_ARCHITECTURE == "RELEASE_BATCH_N1_N10_AUTONOMOUS_TEST_RUNTIME"
    assert BUILD_STATUS == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"


def test_inherited_rc7_identity_defaults_are_unchanged() -> None:
    assert rc7_package.PACKAGE_NAME == "PFC-AITest-DSH-Turnkey-RC7-BANK-WIN10"
    assert rc7_package.MANIFEST_SCHEMA == "pfc.aitest.rc7.package.v1"
    assert rc7_package.BUILD_STATUS == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"


def test_discover_required_runtime_files_covers_every_current_rc72_module() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected = {
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "rc7_runtime").glob("rc72_*.py")
        if path.is_file()
    }
    discovered = set(discover_required_rc72_runtime_files(repo_root))

    assert expected
    assert discovered == expected
    assert "rc7_runtime/rc72_state_machine.py" in discovered
    assert "rc7_runtime/rc72_worker_lifecycle.py" in discovered
    assert "rc7_runtime/rc72_release_convergence.py" in discovered
    assert "rc7_runtime/rc72_official_journey_execution.py" in discovered


def test_promote_manifest_rewrites_identity_and_binds_exact_source() -> None:
    required = (
        "rc7_runtime/rc72_domain.py",
        "rc7_runtime/rc72_state_machine.py",
    )
    manifest = promote_manifest_to_rc72(
        _base_manifest(),
        source_commit=SOURCE_COMMIT,
        required_runtime_files=required,
    )

    assert manifest["schema_version"] == RC72_MANIFEST_SCHEMA
    assert manifest["status"] == BUILD_STATUS
    assert manifest["build_id"] == RC72_BUILD_ID_PREFIX + SOURCE_COMMIT[:12]
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert manifest["package_name"] == RC72_PACKAGE_NAME
    assert manifest["release_family"] == RC72_RELEASE_FAMILY
    assert manifest["architecture"] == RC72_ARCHITECTURE
    assert manifest["required_rc72_runtime_files"] == list(required)
    assert manifest["field_verified"] is False
    assert manifest["bank_final"] is False


def test_promote_manifest_rejects_source_commit_mismatch() -> None:
    base = _base_manifest()
    base["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="SOURCE_COMMIT_MISMATCH"):
        promote_manifest_to_rc72(
            base,
            source_commit=SOURCE_COMMIT,
            required_runtime_files=("rc7_runtime/rc72_domain.py",),
        )


def test_rc7_manifest_cannot_pass_rc72_identity_validation() -> None:
    with pytest.raises(ValueError, match="RC72_MANIFEST_SCHEMA_MISMATCH"):
        validate_rc72_manifest(_base_manifest(), expected_source_commit=SOURCE_COMMIT)


def test_rc72_manifest_requires_all_declared_runtime_files() -> None:
    required = (
        "rc7_runtime/rc72_domain.py",
        "rc7_runtime/rc72_state_machine.py",
    )
    manifest = promote_manifest_to_rc72(
        _base_manifest(),
        source_commit=SOURCE_COMMIT,
        required_runtime_files=required,
    )
    manifest["files"] = [
        {"path": "rc7_runtime/rc72_domain.py", "sha256": "0" * 64, "size": 1}
    ]

    with pytest.raises(ValueError, match="RC72_RUNTIME_FILE_MISSING"):
        validate_rc72_manifest(manifest, expected_source_commit=SOURCE_COMMIT)


def test_rc72_manifest_cannot_claim_field_or_bank_final() -> None:
    manifest = promote_manifest_to_rc72(
        _base_manifest(),
        source_commit=SOURCE_COMMIT,
        required_runtime_files=(),
    )
    manifest["field_verified"] = True
    with pytest.raises(ValueError, match="RC72_FIELD_CLAIM_FORBIDDEN"):
        validate_rc72_manifest(manifest, expected_source_commit=SOURCE_COMMIT)

    manifest["field_verified"] = False
    manifest["bank_final"] = True
    with pytest.raises(ValueError, match="RC72_BANK_FINAL_CLAIM_FORBIDDEN"):
        validate_rc72_manifest(manifest, expected_source_commit=SOURCE_COMMIT)
