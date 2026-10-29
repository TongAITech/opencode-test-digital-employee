from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40


def _attestation_module():
    return importlib.import_module("rc7_release.rc72_target_linux_attestation")


def _observation():
    return {
        "schema": "pfc.aitest.rc7.2.target-linux-observation.v1",
        "source_commit": SOURCE,
        "platform_family": "openEuler",
        "platform_release": "24.03-LTS",
        "architecture": "x86_64",
        "python_version": "3.8.18",
        "shell": "/bin/bash",
        "runner_kind": "APPROVED_SELF_HOSTED_TARGET",
        "runner_identity": "target-linux-runner-01",
    }


class ExternalVerifier:
    kind = "APPROVED_SELF_HOSTED_TARGET_LINUX"

    def __init__(self, payload):
        self.payload = dict(payload)
        self.calls = []

    def verify(self, ref):
        self.calls.append(ref)
        return dict(self.payload)


def test_target_probe_script_exists_is_posix_and_contains_no_install_or_self_approval_commands():
    probe = REPO_ROOT / "packaging" / "rc7.2" / "Q3-TARGET-LINUX-PROBE.sh"
    assert probe.is_file()
    subprocess.run(["bash", "-n", str(probe)], check=True)
    text = probe.read_text(encoding="utf-8")
    assert "/etc/os-release" in text
    assert "uname -m" in text
    assert "SOURCE_COMMIT" in text
    assert "runner_kind" in text
    assert "runner_identity" in text
    lowered = text.lower()
    for forbidden in (
        "apt install",
        "apt-get install",
        "yum install",
        "dnf install",
        "pip install",
        "npm install",
        "curl http",
        "wget http",
        "target_linux_verified=true",
        "field_verified=true",
        "bank_final=true",
        '"decision":"approved"',
        '"status":"pass"',
    ):
        assert forbidden not in lowered


def test_probe_runs_on_generic_linux_and_emits_observation_only(tmp_path):
    probe = REPO_ROOT / "packaging" / "rc7.2" / "Q3-TARGET-LINUX-PROBE.sh"
    output = tmp_path / "observation.json"
    subprocess.run(
        [
            "bash",
            str(probe),
            "--source-commit",
            SOURCE,
            "--runner-kind",
            "GITHUB_HOSTED_GENERIC",
            "--runner-identity",
            "contract-runner",
            "--output",
            str(output),
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "pfc.aitest.rc7.2.target-linux-observation.v1"
    assert payload["source_commit"] == SOURCE
    assert payload["runner_kind"] == "GITHUB_HOSTED_GENERIC"
    assert payload["runner_identity"] == "contract-runner"
    assert payload["platform_family"]
    assert payload["platform_release"]
    assert payload["architecture"]
    assert payload["shell"]
    for forbidden in (
        "status",
        "decision",
        "target_environment_approved",
        "target_linux_verified",
        "field_verified",
        "bank_final",
    ):
        assert forbidden not in payload


def test_attestation_request_is_digest_bound_and_contains_no_approval(tmp_path):
    m = _attestation_module()
    observation = _observation()
    request = m.build_attestation_request(observation)
    expected_digest = hashlib.sha256(
        json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert request["schema"] == "pfc.aitest.rc7.2.target-linux-attestation-request.v1"
    assert request["source_commit"] == SOURCE
    assert request["observation_digest"] == expected_digest
    assert request["runner_identity"] == observation["runner_identity"]
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert request["target_linux_verified"] is False
    assert request["field_verified"] is False
    assert request["bank_final"] is False
    assert "decision" not in request
    assert "target_environment_approved" not in request


def test_untrusted_local_attestation_file_can_never_promote_q3(tmp_path):
    m = _attestation_module()
    observation = _observation()
    digest = m.observation_digest(observation)
    attestation = {
        "schema": "pfc.aitest.rc7.2.target-linux-attestation.v1",
        "decision": "APPROVED",
        "source_commit": SOURCE,
        "observation_digest": digest,
        "platform_family": observation["platform_family"],
        "platform_release": observation["platform_release"],
        "architecture": observation["architecture"],
        "runner_identity": observation["runner_identity"],
        "target_environment_approved": True,
        "evidence_refs": ["file://local-self-approval"],
    }
    path = tmp_path / "attestation.json"
    path.write_text(json.dumps(attestation), encoding="utf-8")
    verifier = m.LocalFileAttestationVerifier(path)
    result = m.evaluate_bound_target_attestation(
        observation=observation,
        attestation_ref=str(path),
        verifier=verifier,
    )
    assert verifier.kind == "UNTRUSTED_LOCAL_FILE_ATTESTATION"
    assert result["status"] == "HOLD"
    assert result["reason"] == "UNTRUSTED_TARGET_LINUX_VERIFIER"
    assert result["target_linux_verified"] is False


def test_trusted_external_attestation_must_bind_exact_observation_digest():
    m = _attestation_module()
    observation = _observation()
    payload = {
        "schema": "pfc.aitest.rc7.2.target-linux-attestation.v1",
        "decision": "APPROVED",
        "source_commit": SOURCE,
        "observation_digest": "0" * 64,
        "platform_family": observation["platform_family"],
        "platform_release": observation["platform_release"],
        "architecture": observation["architecture"],
        "runner_identity": observation["runner_identity"],
        "target_environment_approved": True,
        "evidence_refs": ["attestation://trusted/01"],
    }
    result = m.evaluate_bound_target_attestation(
        observation=observation,
        attestation_ref="attestation://trusted/01",
        verifier=ExternalVerifier(payload),
    )
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_OBSERVATION_DIGEST_MISMATCH"
    assert result["target_linux_verified"] is False


def test_trusted_external_attestation_can_release_hold_only_when_digest_source_and_machine_match():
    m = _attestation_module()
    observation = _observation()
    payload = {
        "schema": "pfc.aitest.rc7.2.target-linux-attestation.v1",
        "decision": "APPROVED",
        "source_commit": SOURCE,
        "observation_digest": m.observation_digest(observation),
        "platform_family": observation["platform_family"],
        "platform_release": observation["platform_release"],
        "architecture": observation["architecture"],
        "runner_identity": observation["runner_identity"],
        "target_environment_approved": True,
        "evidence_refs": ["attestation://trusted/01", "probe://target/01"],
    }
    verifier = ExternalVerifier(payload)
    result = m.evaluate_bound_target_attestation(
        observation=observation,
        attestation_ref="attestation://trusted/01",
        verifier=verifier,
    )
    assert verifier.calls == ["attestation://trusted/01"]
    assert result["status"] == "PASS"
    assert result["target_linux_verified"] is True
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["observation_digest"] == payload["observation_digest"]


def test_source_lineage_in_observation_is_required_before_request_or_evaluation():
    m = _attestation_module()
    observation = _observation()
    observation["source_commit"] = "not-a-sha"
    with pytest.raises(ValueError, match="TARGET_LINUX_OBSERVATION_SOURCE_INVALID"):
        m.build_attestation_request(observation)
    with pytest.raises(ValueError, match="TARGET_LINUX_OBSERVATION_SOURCE_INVALID"):
        m.observation_digest(observation)
