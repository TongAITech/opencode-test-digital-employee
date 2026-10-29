from __future__ import annotations

import importlib

import pytest

SOURCE = "a" * 40
REQUIRED_PACKAGE_FILES = (
    "SOURCE_COMMIT",
    "packaging/rc7.2/Q3-FIELD-HANDOFF.sh",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "packaging/rc7.2/AITEST.sh",
    "rc7_release/rc72_target_linux_attestation.py",
    "rc7_release/rc72_target_linux_reality.py",
)


def _module():
    return importlib.import_module("rc7_release.rc72_target_linux_reality")


def _bound():
    return importlib.import_module("rc7_release.rc72_target_linux_attestation")


def _observation(**overrides):
    payload = {"source_commit": SOURCE, "platform_family": "openEuler", "platform_release": "24.03-LTS", "architecture": "x86_64", "python_version": "3.8.18", "shell": "/bin/bash", "runner_kind": "APPROVED_SELF_HOSTED_TARGET", "runner_identity": "target-linux-runner-01"}
    payload.update(overrides)
    return payload


def _bound_observation(observation):
    payload = dict(observation)
    payload["schema"] = "pfc.aitest.rc7.2.target-linux-observation.v1"
    return payload


def _package(observation, **overrides):
    payload = {"schema": "pfc.aitest.rc7.2.q3-target-package-evidence.v1", "source_commit": observation["source_commit"], "package_source_commit": observation["source_commit"], "package_source_match": True, "package_root": "/opt/rc72", "probe": "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh", "attestation_module": "rc7_release/rc72_target_linux_attestation.py", "reality_module": "rc7_release/rc72_target_linux_reality.py", "shell_entrypoint": "packaging/rc7.2/AITEST.sh", "shell_syntax_verified": True, "python_runtime": "/usr/bin/python3", "python_origin": "TARGET_HOST_RUNTIME", "runner_kind": observation["runner_kind"], "runner_identity": observation["runner_identity"], "critical_files": {path: "2" * 64 for path in REQUIRED_PACKAGE_FILES}, "network_install_performed": False, "target_linux_verified": False, "field_verified": False, "bank_final": False}
    payload.update(overrides)
    return payload


def _attestation(observation, package, **overrides):
    b = _bound()
    bound_observation = _bound_observation(observation)
    payload = {"schema": "pfc.aitest.rc7.2.target-linux-attestation.v1", "decision": "APPROVED", "source_commit": SOURCE, "observation_digest": b.observation_digest(bound_observation), "package_evidence_digest": b.package_evidence_digest(package, bound_observation), "platform_family": observation["platform_family"], "platform_release": observation["platform_release"], "architecture": observation["architecture"], "runner_identity": observation["runner_identity"], "target_environment_approved": True, "evidence_refs": ["attestation://target-linux/01", "probe://uname/01", "package://target/01"]}
    payload.update(overrides)
    return payload


class StaticVerifier:
    def __init__(self, kind, attestation):
        self.kind = kind
        self.attestation = dict(attestation)
        self.calls = []
    def verify(self, ref):
        self.calls.append(ref)
        return dict(self.attestation)


def test_missing_target_attestation_is_hold_not_pass():
    m = _module()
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=_observation(), package_evidence=None, attestation_ref=None, verifier=None)
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_ATTESTATION_REQUIRED"


def test_generic_github_ubuntu_is_never_target_linux_pass():
    m = _module()
    observation = _observation(platform_family="Ubuntu", platform_release="24.04", runner_kind="GITHUB_HOSTED_GENERIC", runner_identity="github-hosted-linux")
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=None, attestation_ref="attestation://fake/ubuntu", verifier=StaticVerifier("BANK_FIELD_TARGET_LINUX", {}))
    assert result["status"] == "HOLD"
    assert result["reason"] == "GENERIC_LINUX_PROXY_NOT_TARGET"


def test_contract_verifier_cannot_promote_target_linux():
    m = _module()
    observation = _observation()
    package = _package(observation)
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=package, attestation_ref="attestation://contract/01", verifier=StaticVerifier("CONTRACT_VERIFIER", _attestation(observation, package)))
    assert result["status"] == "HOLD"
    assert result["reason"] == "UNTRUSTED_TARGET_LINUX_VERIFIER"


def test_legacy_reality_path_cannot_pass_trusted_target_without_package_binding():
    m = _module()
    observation = _observation()
    package = _package(observation)
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=None, attestation_ref="attestation://target-linux/01", verifier=StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation(observation, package)))
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_PACKAGE_EVIDENCE_REQUIRED"
    assert result["target_linux_verified"] is False


def test_trusted_approved_self_hosted_target_can_pass_only_with_dual_binding():
    m = _module()
    observation = _observation()
    package = _package(observation)
    verifier = StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation(observation, package))
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=package, attestation_ref="attestation://target-linux/01", verifier=verifier)
    assert result["status"] == "PASS"
    assert result["target_linux_verified"] is True
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["observation_digest"]
    assert result["package_evidence_digest"]


def test_trusted_bank_target_can_mark_field_verified_but_never_bank_final():
    m = _module()
    observation = _observation(runner_kind="BANK_FIELD_TARGET", runner_identity="bank-linux-node-01")
    package = _package(observation)
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=package, attestation_ref="attestation://bank/target-linux/01", verifier=StaticVerifier("BANK_FIELD_TARGET_LINUX", _attestation(observation, package)))
    assert result["status"] == "PASS"
    assert result["field_verified"] is True
    assert result["bank_final"] is False


def test_source_lineage_mismatch_is_fail_closed():
    m = _module()
    observation = _observation()
    package = _package(observation)
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=package, attestation_ref="attestation://wrong", verifier=StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation(observation, package, source_commit="b" * 40)))
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_SOURCE_COMMIT_MISMATCH"


@pytest.mark.parametrize("field", ["platform_family", "platform_release", "architecture", "runner_identity"])
def test_incomplete_target_platform_identity_is_hold(field):
    m = _module()
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=_observation(**{field: ""}), package_evidence=None, attestation_ref="attestation://target-linux/01", verifier=None)
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_PLATFORM_IDENTITY_INCOMPLETE"


def test_package_digest_mismatch_is_fail_closed_on_reality_facade():
    m = _module()
    observation = _observation()
    package = _package(observation)
    attestation = _attestation(observation, package, package_evidence_digest="0" * 64)
    result = m.evaluate_target_linux_reality(source_commit=SOURCE, observation=observation, package_evidence=package, attestation_ref="attestation://target-linux/bad-package", verifier=StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", attestation))
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_PACKAGE_EVIDENCE_DIGEST_MISMATCH"
