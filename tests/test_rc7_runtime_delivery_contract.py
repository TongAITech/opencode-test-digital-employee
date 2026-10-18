from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rc7_release.optional_plugin_payload import OPTIONAL_PLUGIN_NAMES
from rc7_release.runtime_delivery_contract import (
    OCR_CV_MARKER,
    RuntimeDeliveryContractError,
    verify_runtime_delivery,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lock() -> dict:
    return {
        "payloads": {
            "python": {
                "relative_target": "workspace-template/runtime/python/python.exe",
                "required_for_delivery": True,
            },
            "controlled_browser": {
                "relative_target": "workspace-template/runtime/browser/chrome-win64/chrome.exe",
                "required_for_delivery": True,
            },
            "codegraph": {
                "relative_target": "workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe",
                "required_for_delivery": True,
            },
            "local_ocr_cv": {
                "relative_target": "workspace-template/runtime/python",
                "required_for_delivery": True,
            },
            "gitnexus": {
                "relative_target": "workspace-template/runtime/node-execution/node_modules/gitnexus",
                "required_for_delivery": False,
            },
        }
    }


def _manifest(browser: bool = True, codegraph: bool = True) -> dict:
    return {
        "package_local_browser": {"bundled": browser},
        "package_local_codegraph": {"bundled": codegraph},
    }


def _full_layout(root: Path) -> None:
    _write_json(root / "runtime-lock.json", _lock())
    _write_json(root / "PACKAGE_MANIFEST.json", _manifest())
    files = [
        root / "workspace-template/runtime/python/python.exe",
        root / "workspace-template/runtime/browser/chrome-win64/chrome.exe",
        root / "workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe",
        root / OCR_CV_MARKER,
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"qualified-runtime")


def _with_turnkey_optional_bundle(lock: dict) -> dict:
    lock = json.loads(json.dumps(lock))
    lock["payloads"]["dsh_optional_plugins"] = {
        "relative_target": "rc7_release/vendor/dsh-optional-plugins-payload.zip",
        "required_for_delivery": False,
        "turnkey_bundle_required": True,
    }
    return lock


def _write_optional_bundle(root: Path, plugins=OPTIONAL_PLUGIN_NAMES, *, manifest_status: str = "PASS") -> None:
    target = root / "rc7_release/vendor/dsh-optional-plugins-payload.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    bundled = list(plugins)
    missing = [name for name in OPTIONAL_PLUGIN_NAMES if name not in bundled]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in bundled:
            if name.startswith("@"):
                scope, package = name.split("/", 1)
                member = "node_modules/%s/%s/package.json" % (scope, package)
            else:
                member = "node_modules/%s/package.json" % name
            archive.writestr(member, json.dumps({"name": name, "version": "test"}))
        archive.writestr(
            "payload-manifest.json",
            json.dumps({"status": manifest_status, "bundled": bundled, "missing": missing}),
        )


def test_thin_python_only_package_is_rejected_with_named_missing_payloads(tmp_path: Path) -> None:
    _write_json(tmp_path / "runtime-lock.json", _lock())
    _write_json(tmp_path / "PACKAGE_MANIFEST.json", _manifest(browser=False, codegraph=False))
    python = tmp_path / "workspace-template/runtime/python/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")

    with pytest.raises(RuntimeDeliveryContractError) as exc:
        verify_runtime_delivery(tmp_path)

    message = str(exc.value)
    assert "REQUIRED_PAYLOAD_MISSING:codegraph,controlled_browser" in message
    assert "REQUIRED_CAPABILITY_MARKER_MISSING:local_ocr_cv" in message
    assert "REQUIRED_PAYLOAD_MANIFEST_FALSE:codegraph,controlled_browser" in message


def test_full_required_runtime_layout_passes_and_ordinary_optional_payload_may_be_absent(tmp_path: Path) -> None:
    _full_layout(tmp_path)
    result = verify_runtime_delivery(tmp_path)

    assert result["status"] == "PASS"
    assert result["delivery_runtime_complete"] is True
    assert result["required_payload_count"] == 4
    assert result["turnkey_bundle_count"] == 0
    rows = {row["payload"]: row for row in result["payloads"]}
    assert rows["gitnexus"]["required_for_delivery"] is False
    assert rows["gitnexus"]["present"] is False


def test_turnkey_optional_bundle_is_required_without_changing_core_payload_count(tmp_path: Path) -> None:
    _full_layout(tmp_path)
    _write_json(tmp_path / "runtime-lock.json", _with_turnkey_optional_bundle(_lock()))

    with pytest.raises(RuntimeDeliveryContractError, match="TURNKEY_BUNDLE_INCOMPLETE:dsh_optional_plugins:ARCHIVE_MISSING"):
        verify_runtime_delivery(tmp_path)


def test_partial_turnkey_optional_bundle_is_rejected(tmp_path: Path) -> None:
    _full_layout(tmp_path)
    _write_json(tmp_path / "runtime-lock.json", _with_turnkey_optional_bundle(_lock()))
    _write_optional_bundle(tmp_path, OPTIONAL_PLUGIN_NAMES[:-1], manifest_status="PARTIAL")

    with pytest.raises(RuntimeDeliveryContractError, match="TURNKEY_BUNDLE_INCOMPLETE:dsh_optional_plugins"):
        verify_runtime_delivery(tmp_path)


def test_complete_turnkey_optional_bundle_passes_and_reports_four_plugins(tmp_path: Path) -> None:
    _full_layout(tmp_path)
    _write_json(tmp_path / "runtime-lock.json", _with_turnkey_optional_bundle(_lock()))
    _write_optional_bundle(tmp_path)

    result = verify_runtime_delivery(tmp_path)
    assert result["status"] == "PASS"
    assert result["required_payload_count"] == 4
    assert result["turnkey_bundle_count"] == 1
    bundle = result["turnkey_bundles"][0]
    assert bundle["status"] == "PASS"
    assert set(bundle["bundled"]) == set(OPTIONAL_PLUGIN_NAMES)
    rows = {row["payload"]: row for row in result["payloads"]}
    assert rows["dsh_optional_plugins"]["required_for_delivery"] is False
    assert rows["dsh_optional_plugins"]["turnkey_bundle_required"] is True
    assert rows["dsh_optional_plugins"]["turnkey_bundle_status"] == "PASS"


def test_empty_required_directory_is_not_delivery_payload(tmp_path: Path) -> None:
    lock = {"payloads": {"jdk": {"relative_target": "workspace-template/runtime/java", "required_for_delivery": True}}}
    _write_json(tmp_path / "runtime-lock.json", lock)
    (tmp_path / "workspace-template/runtime/java").mkdir(parents=True)

    with pytest.raises(RuntimeDeliveryContractError, match="REQUIRED_PAYLOAD_MISSING:jdk"):
        verify_runtime_delivery(tmp_path)


def test_unsafe_runtime_target_is_rejected(tmp_path: Path) -> None:
    lock = {"payloads": {"bad": {"relative_target": "../outside.exe", "required_for_delivery": True}}}
    _write_json(tmp_path / "runtime-lock.json", lock)

    with pytest.raises(RuntimeDeliveryContractError, match="UNSAFE_RUNTIME_TARGET"):
        verify_runtime_delivery(tmp_path)


def test_python_presence_cannot_fake_local_ocr_cv_capability(tmp_path: Path) -> None:
    lock = {"payloads": {"local_ocr_cv": {"relative_target": "workspace-template/runtime/python", "required_for_delivery": True}}}
    _write_json(tmp_path / "runtime-lock.json", lock)
    python = tmp_path / "workspace-template/runtime/python/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")

    with pytest.raises(RuntimeDeliveryContractError, match="REQUIRED_CAPABILITY_MARKER_MISSING:local_ocr_cv"):
        verify_runtime_delivery(tmp_path)
