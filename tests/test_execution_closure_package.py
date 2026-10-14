from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc6_release.package import BUILD_STATUS, build_package, verify_package


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


REQUIRED_EXECUTION_CLOSURE_FILES = {
    "rc6_runtime/executable_spec.py",
    "rc6_runtime/automation.py",
    "rc6_runtime/runner_manifest.py",
    "rc6_runtime/diagnosis.py",
    "rc6_runtime/recovery.py",
    "rc6_runtime/recovery_adapters.py",
    "rc6_runtime/execution_overlay.py",
    "rc6_release/execution_closure_mcp.py",
    "rc6_release/execution_closure_hardening.py",
    "rc6_release/recovery_adapter_registry.py",
    "rc6_release/mcp_server.py",
}


def test_turnkey_package_contains_execution_closure_runtime_and_remains_not_bank_final(tmp_path):
    package_root = build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)
    result = verify_package(package_root)
    assert result["status"] == "PASS"
    assert result["release_status"] == BUILD_STATUS == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"

    for relative in REQUIRED_EXECUTION_CLOSURE_FILES:
        assert (package_root / relative).is_file(), relative

    manifest = json.loads((package_root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert REQUIRED_EXECUTION_CLOSURE_FILES.issubset(paths)
    assert manifest["bank_field_pass"] is False
    assert manifest["autonomous_testing_pass"] is False
    assert manifest["full_chain_real"] is False


def test_verify_package_tolerates_python_cache_and_runtime_state(tmp_path):
    package_root = build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)

    cache = package_root / "rc6_release" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "package.cpython-38.pyc").write_bytes(b"runtime-bytecode")
    state = package_root / "runtime-state"
    state.mkdir()
    (state / "dsh-web.log").write_text("runtime log", encoding="utf-8")
    (state / "rc6.cordis.yml").write_text("runtime patch", encoding="utf-8")

    assert verify_package(package_root)["status"] == "PASS"


def test_verify_package_still_rejects_untracked_source_file(tmp_path):
    package_root = build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)
    (package_root / "rc6_runtime" / "rogue.py").write_text("raise SystemExit('rogue')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="PACKAGE_CHECKSUM_COVERAGE_MISMATCH"):
        verify_package(package_root)
