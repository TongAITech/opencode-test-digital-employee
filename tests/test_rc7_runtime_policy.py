from __future__ import annotations

import json
from pathlib import Path


def _policy():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "runtime-lock.json").read_text(encoding="utf-8"))


def test_runtime_policy_is_capability_based_and_resolved_versions_live_in_package_manifest():
    policy = _policy()
    assert policy["version_policy"] == "CAPABILITY_BASED_NO_EXACT_VERSION_PIN"
    assert policy["payload_policy"]["resolved_version_and_sha_authority"] == "PACKAGE_MANIFEST.json"

    payloads = policy["payloads"]
    for name, payload in payloads.items():
        assert "version" not in payload, "%s must not pin an exact version in source policy" % name
        assert "sha256" not in payload, "%s must not pin build hash in source policy" % name
        assert payload.get("resolution"), "%s must declare capability resolution policy" % name


def test_delivery_required_offline_capabilities_have_canonical_package_targets():
    policy = _policy()
    payloads = policy["payloads"]

    assert payloads["python"]["required_for_delivery"] is True
    assert payloads["python"]["relative_target"] == "workspace-template/runtime/python/python.exe"

    assert payloads["controlled_browser"]["required_for_delivery"] is True
    assert payloads["controlled_browser"]["relative_target"] == "workspace-template/runtime/browser/chrome-win64/chrome.exe"

    assert payloads["codegraph"]["required_for_delivery"] is True
    assert payloads["codegraph"]["relative_target"] == "workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe"
    assert payloads["codegraph"]["change_truth_authority"] is False
    assert payloads["codegraph"]["actual_coverage_authority"] is False


def test_dsh_remains_field_execution_plane_not_fake_bundled_payload():
    policy = _policy()
    dsh = policy["external_capabilities"]["dsh"]
    assert dsh["role"] == "AI_EXECUTION_PLANE"
    assert dsh["bundled_in_turnkey_zip"] is False
    assert dsh["required_for_real_mission"] is True
    assert dsh["proof_authority"] == "R1_DSH_RUNTIME_PROOF_AND_TASK_SCOPED_TOOL_RECEIPTS"
