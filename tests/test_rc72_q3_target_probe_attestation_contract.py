from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40
REQUIRED_PACKAGE_FILES = (
    "SOURCE_COMMIT",
    "packaging/rc7.2/Q3-FIELD-HANDOFF.sh",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "packaging/rc7.2/AITEST.sh",
    "rc7_release/rc72_target_linux_attestation.py",
    "rc7_release/rc72_target_linux_reality.py",
)


def _attestation_module():
    return importlib.import_module("rc7_release.rc72_target_linux_attestation")


def _git_bash_executable():
    if os.name != "nt":
        return shutil.which("bash") or "bash"
    override = os.environ.get("PFC_GIT_BASH")
    candidates = [Path(override)] if override else []
    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.extend([git_path.with_name("bash.exe"), git_path.parent.parent / "bin" / "bash.exe"])
    for env_name in ("ProgramW6432", "ProgramFiles"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise AssertionError("GIT_BASH_EXECUTABLE_NOT_FOUND")


def _bash_path(path):
    if os.name != "nt":
        return str(path)
    bash = _git_bash_executable()
    return subprocess.check_output([bash, "-lc", 'cygpath -u "$1"', "bash", str(path)], text=True).strip()


def _observation(**overrides):
    payload = {
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
    payload.update(overrides)
    return payload


def _package_evidence(observation=None, **overrides):
    observation = observation or _observation()
    payload = {
        "schema": "pfc.aitest.rc7.2.q3-target-package-evidence.v1",
        "source_commit": observation["source_commit"],
        "package_source_commit": observation["source_commit"],
        "package_source_match": True,
        "package_root": "/opt/rc72",
        "probe": "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
        "attestation_module": "rc7_release/rc72_target_linux_attestation.py",
        "reality_module": "rc7_release/rc72_target_linux_reality.py",
        "shell_entrypoint": "packaging/rc7.2/AITEST.sh",
        "shell_syntax_verified": True,
        "python_runtime": "/usr/bin/python3",
        "python_origin": "TARGET_HOST_RUNTIME",
        "runner_kind": observation["runner_kind"],
        "runner_identity": observation["runner_identity"],
        "critical_files": {path: "1" * 64 for path in REQUIRED_PACKAGE_FILES},
        "network_install_performed": False,
        "target_linux_verified": False,
        "field_verified": False,
        "bank_final": False,
    }
    payload.update(overrides)
    return payload


class ExternalVerifier:
    kind = "APPROVED_SELF_HOSTED_TARGET_LINUX"

    def __init__(self, payload):
        self.payload = dict(payload)
        self.calls = []

    def verify(self, ref):
        self.calls.append(ref)
        return dict(self.payload)


def _approved_attestation(m, observation, package_evidence, **overrides):
    payload = {
        "schema": "pfc.aitest.rc7.2.target-linux-attestation.v1",
        "decision": "APPROVED",
        "source_commit": observation["source_commit"],
        "observation_digest": m.observation_digest(observation),
        "package_evidence_digest": m.package_evidence_digest(package_evidence, observation),
        "platform_family": observation["platform_family"],
        "platform_release": observation["platform_release"],
        "architecture": observation["architecture"],
        "runner_identity": observation["runner_identity"],
        "target_environment_approved": True,
        "evidence_refs": ["attestation://trusted/01", "probe://target/01", "package://target/01"],
    }
    payload.update(overrides)
    return payload


def test_target_probe_script_exists_is_posix_and_contains_no_install_or_self_approval_commands():
    probe = REPO_ROOT / "packaging" / "rc7.2" / "Q3-TARGET-LINUX-PROBE.sh"
    assert probe.is_file()
    subprocess.run([_git_bash_executable(), "-n", _bash_path(probe)], check=True)
    lowered = probe.read_text(encoding="utf-8").lower()
    for forbidden in ("apt install", "apt-get install", "yum install", "dnf install", "pip install", "npm install", "curl http", "wget http", "target_linux_verified=true", "field_verified=true", "bank_final=true", '"decision":"approved"', '"status":"pass"'):
        assert forbidden not in lowered


def test_probe_runs_on_generic_linux_and_emits_observation_only(tmp_path):
    probe = REPO_ROOT / "packaging" / "rc7.2" / "Q3-TARGET-LINUX-PROBE.sh"
    output = tmp_path / "observation.json"
    subprocess.run([_git_bash_executable(), _bash_path(probe), "--source-commit", SOURCE, "--runner-kind", "GITHUB_HOSTED_GENERIC", "--runner-identity", "contract-runner", "--output", _bash_path(output)], check=True, cwd=REPO_ROOT)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "pfc.aitest.rc7.2.target-linux-observation.v1"
    assert payload["source_commit"] == SOURCE
    for forbidden in ("status", "decision", "target_environment_approved", "target_linux_verified", "field_verified", "bank_final"):
        assert forbidden not in payload


def test_attestation_request_binds_observation_and_package_evidence_without_approval():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    request = m.build_attestation_request(observation, package)
    expected_observation = hashlib.sha256(json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert request["observation_digest"] == expected_observation
    assert request["package_evidence_bound"] is True
    assert request["package_evidence_digest"] == m.package_evidence_digest(package, observation)
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert request["target_linux_verified"] is False
    assert request["field_verified"] is False
    assert request["bank_final"] is False
    assert "decision" not in request


def test_observation_only_request_is_explicitly_unbound_and_cannot_imply_target_pass():
    m = _attestation_module()
    request = m.build_attestation_request(_observation())
    assert request["package_evidence_bound"] is False
    assert request["package_evidence_digest"] is None
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert request["target_linux_verified"] is False


def test_untrusted_local_attestation_file_can_never_promote_q3(tmp_path):
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    attestation = _approved_attestation(m, observation, package, evidence_refs=["file://local-self-approval"])
    path = tmp_path / "attestation.json"
    path.write_text(json.dumps(attestation), encoding="utf-8")
    verifier = m.LocalFileAttestationVerifier(path)
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=package, attestation_ref=str(path), verifier=verifier)
    assert result["status"] == "HOLD"
    assert result["reason"] == "UNTRUSTED_TARGET_LINUX_VERIFIER"


def test_trusted_verifier_cannot_promote_without_package_evidence():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=None, attestation_ref="attestation://trusted/01", verifier=ExternalVerifier(_approved_attestation(m, observation, package)))
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_PACKAGE_EVIDENCE_REQUIRED"
    assert result["target_linux_verified"] is False


def test_trusted_attestation_must_bind_exact_observation_digest():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    payload = _approved_attestation(m, observation, package, observation_digest="0" * 64)
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=package, attestation_ref="attestation://trusted/01", verifier=ExternalVerifier(payload))
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_OBSERVATION_DIGEST_MISMATCH"


def test_trusted_attestation_must_bind_exact_package_evidence_digest():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    payload = _approved_attestation(m, observation, package, package_evidence_digest="0" * 64)
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=package, attestation_ref="attestation://trusted/01", verifier=ExternalVerifier(payload))
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_PACKAGE_EVIDENCE_DIGEST_MISMATCH"


def test_tampered_package_evidence_fails_before_external_approval():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation, package_source_match=False)
    verifier = ExternalVerifier({})
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=package, attestation_ref="attestation://trusted/01", verifier=verifier)
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_PACKAGE_SOURCE_MISMATCH"
    assert verifier.calls == []


def test_trusted_external_attestation_can_release_hold_only_when_both_digests_source_and_machine_match():
    m = _attestation_module()
    observation = _observation()
    package = _package_evidence(observation)
    payload = _approved_attestation(m, observation, package)
    verifier = ExternalVerifier(payload)
    result = m.evaluate_bound_target_attestation(observation=observation, package_evidence=package, attestation_ref="attestation://trusted/01", verifier=verifier)
    assert verifier.calls == ["attestation://trusted/01"]
    assert result["status"] == "PASS"
    assert result["target_linux_verified"] is True
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["observation_digest"] == payload["observation_digest"]
    assert result["package_evidence_digest"] == payload["package_evidence_digest"]


def test_source_lineage_in_observation_is_required_before_request_or_evaluation():
    m = _attestation_module()
    observation = _observation(source_commit="not-a-sha")
    with pytest.raises(ValueError, match="TARGET_LINUX_OBSERVATION_SOURCE_INVALID"):
        m.build_attestation_request(observation)
    with pytest.raises(ValueError, match="TARGET_LINUX_OBSERVATION_SOURCE_INVALID"):
        m.observation_digest(observation)
