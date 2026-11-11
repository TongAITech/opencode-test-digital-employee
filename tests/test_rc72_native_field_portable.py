"""Native RC7.2 package contracts: platform identity, Windows contamination and sealed inventory."""
import json
from pathlib import Path

import pytest

from rc7_release.rc72_native_field_portable import (
    NativeFieldError,
    _check_no_windows_payload,
    _write_seal,
    target_identity,
    verify_package,
)


def _sealed_fixture(tmp_path):
    identity = target_identity()
    root = tmp_path / identity["package_name"]
    root.mkdir()
    (root / "SOURCE_COMMIT").write_text("a" * 40 + "\n")
    (root / "BUILD_ID").write_text("RC7.2-NATIVE-" + "a" * 12 + "\n")
    required = [
        "README-FIRST.md", "start-rc7.2.sh", "packaging/rc7.2/AITEST.sh",
        "packaging/rc7.2/NATIVE-FIELD-AITEST.sh",
        "packaging/rc7.2/dsh-alpha/PAYLOAD-STATUS.json",
        "packaging/rc7.2/dsh-alpha/install-dsh-alpha.sh",
        "workspace-template/runtime/python/bin/python3",
        "workspace-template/runtime/node/bin/node",
        "workspace-template/runtime/browser/browserskill/bsk",
        "workspace-template/runtime/browser/browserskill-extension/manifest.json",
        "workspace-template/runtime/node-execution/node_modules/playwright/package.json",
        "workspace-template/runtime/code-intelligence/codegraph/" + (
            "codegraph-server-linux-x64" if identity["platform"] == "linux" and identity["architecture"] == "x86_64"
            else "codegraph-server-linux-arm64" if identity["platform"] == "linux"
            else "codegraph-server-darwin-x64" if identity["architecture"] == "x86_64"
            else "codegraph-server-darwin-arm64"
        ),
        "workspace-template/runtime/k6/k6", "workspace-template/runtime/ripgrep/rg",
        "workspace-template/runtime/java/bin/java", "workspace-template/runtime/maven/bin/mvn",
        "workspace-template/runtime/allure/bin/allure", "workspace-template/runtime/maven-repository/seed.jar",
        "workspace-template/runtime/zap/ZAP_2.17.0/zap.sh",
        "rc7_release/vendor/dsh-plugins-payload.zip",
    ]
    for rel in required:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fixture")
    alpha = {
        "status": "LICENSE_HOLD_NOT_BUNDLED",
        "source_commit": "f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4",
    }
    (root / "packaging/rc7.2/dsh-alpha/PAYLOAD-STATUS.json").write_text(json.dumps(alpha))
    metadata = {
        "schema": "pfc.aitest.rc7.2.native-field.v1",
        "status": "NATIVE_FIELD_CANDIDATE",
        **identity,
        "source_commit": "a" * 40,
        "field_verified": False,
        "bank_final": False,
        "real_mission_pass": False,
        "q3_target_verified": False,
        "dsh_plugins": {"dsh_alpha": {"status": "LICENSE_HOLD_NOT_BUNDLED"}},
    }
    _write_seal(root, metadata)
    return root


def test_native_package_verifies_exact_inventory_and_keeps_field_claims_false(tmp_path):
    root = _sealed_fixture(tmp_path)
    result = verify_package(root, expected_source_commit="a" * 40)
    assert result["status"] == "PASS"
    assert result["checksum_coverage"] == "EXACT"
    assert result["field_verified"] is False
    assert result["bank_final"] is False


def test_native_package_rejects_checksum_tampering(tmp_path):
    root = _sealed_fixture(tmp_path)
    (root / "README-FIRST.md").write_text("tampered")
    with pytest.raises(NativeFieldError, match="CHECKSUM_COVERAGE_MISMATCH"):
        verify_package(root)


def test_native_package_rejects_windows_payload_by_extension_and_pe_magic(tmp_path):
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "start.cmd").write_text("@echo off")
    with pytest.raises(NativeFieldError, match="WINDOWS_PAYLOAD_IN_NATIVE_PACKAGE"):
        _check_no_windows_payload(root)
    (root / "start.cmd").unlink()
    (root / "renamed-native").write_bytes(b"MZ\x90\x00fake-pe")
    with pytest.raises(NativeFieldError, match="WINDOWS_PE_PAYLOAD_IN_NATIVE_PACKAGE"):
        _check_no_windows_payload(root)


def test_target_identity_is_explicit_and_never_windows():
    identity = target_identity()
    assert identity["platform"] in {"linux", "darwin"}
    assert identity["architecture"] in {"x86_64", "arm64"}
    assert "WINDOWS" not in identity["package_name"]
