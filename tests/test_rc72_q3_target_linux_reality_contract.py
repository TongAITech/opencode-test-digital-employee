from __future__ import annotations

import importlib

import pytest


SOURCE = "a" * 40


def _module():
    return importlib.import_module("rc7_release.rc72_target_linux_reality")


def _observation(**overrides):
    payload = {
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


def _attestation(**overrides):
    payload = {
        "decision": "APPROVED",
        "source_commit": SOURCE,
        "platform_family": "openEuler",
        "platform_release": "24.03-LTS",
        "architecture": "x86_64",
        "runner_identity": "target-linux-runner-01",
        "target_environment_approved": True,
        "evidence_refs": ["attestation://target-linux/01", "probe://uname/01"],
    }
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
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref=None,
        verifier=None,
    )
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_ATTESTATION_REQUIRED"
    assert result["target_linux_verified"] is False
    assert result["field_verified"] is False
    assert result["bank_final"] is False


def test_generic_github_ubuntu_is_never_target_linux_pass():
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(
            platform_family="Ubuntu",
            platform_release="24.04",
            runner_kind="GITHUB_HOSTED_GENERIC",
            runner_identity="github-hosted-linux",
        ),
        attestation_ref="attestation://fake/ubuntu",
        verifier=StaticVerifier(
            "CONTRACT_VERIFIER",
            _attestation(
                platform_family="Ubuntu",
                platform_release="24.04",
                runner_identity="github-hosted-linux",
            ),
        ),
    )
    assert result["status"] == "HOLD"
    assert result["reason"] == "GENERIC_LINUX_PROXY_NOT_TARGET"
    assert result["target_linux_verified"] is False
    assert result["field_verified"] is False


def test_contract_verifier_cannot_promote_target_linux_even_when_payload_says_approved():
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref="attestation://contract/01",
        verifier=StaticVerifier("CONTRACT_VERIFIER", _attestation()),
    )
    assert result["status"] == "HOLD"
    assert result["reason"] == "UNTRUSTED_TARGET_LINUX_VERIFIER"
    assert result["target_linux_verified"] is False
    assert result["field_verified"] is False


def test_trusted_approved_self_hosted_target_can_pass_without_claiming_bank_field():
    m = _module()
    verifier = StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation())
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref="attestation://target-linux/01",
        verifier=verifier,
    )
    assert verifier.calls == ["attestation://target-linux/01"]
    assert result["status"] == "PASS"
    assert result["target_linux_verified"] is True
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["verifier_kind"] == "APPROVED_SELF_HOSTED_TARGET_LINUX"


def test_trusted_bank_target_can_mark_field_verified_but_never_bank_final():
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(runner_kind="BANK_FIELD_TARGET", runner_identity="bank-linux-node-01"),
        attestation_ref="attestation://bank/target-linux/01",
        verifier=StaticVerifier(
            "BANK_FIELD_TARGET_LINUX",
            _attestation(runner_identity="bank-linux-node-01"),
        ),
    )
    assert result["status"] == "PASS"
    assert result["target_linux_verified"] is True
    assert result["field_verified"] is True
    assert result["bank_final"] is False


def test_source_lineage_mismatch_is_fail_closed():
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref="attestation://target-linux/wrong-source",
        verifier=StaticVerifier(
            "APPROVED_SELF_HOSTED_TARGET_LINUX",
            _attestation(source_commit="b" * 40),
        ),
    )
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_SOURCE_COMMIT_MISMATCH"
    assert result["target_linux_verified"] is False


@pytest.mark.parametrize("field", ["platform_family", "platform_release", "architecture", "runner_identity"])
def test_incomplete_target_platform_identity_is_hold(field):
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(**{field: ""}),
        attestation_ref="attestation://target-linux/01",
        verifier=StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation()),
    )
    assert result["status"] == "HOLD"
    assert result["reason"] == "TARGET_LINUX_PLATFORM_IDENTITY_INCOMPLETE"
    assert result["target_linux_verified"] is False


def test_unapproved_target_or_missing_evidence_cannot_pass():
    m = _module()
    denied = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref="attestation://target-linux/denied",
        verifier=StaticVerifier(
            "APPROVED_SELF_HOSTED_TARGET_LINUX",
            _attestation(target_environment_approved=False),
        ),
    )
    assert denied["status"] == "HOLD"
    assert denied["reason"] == "TARGET_LINUX_ENVIRONMENT_NOT_APPROVED"

    no_evidence = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(),
        attestation_ref="attestation://target-linux/no-evidence",
        verifier=StaticVerifier(
            "APPROVED_SELF_HOSTED_TARGET_LINUX",
            _attestation(evidence_refs=[]),
        ),
    )
    assert no_evidence["status"] == "HOLD"
    assert no_evidence["reason"] == "TARGET_LINUX_EVIDENCE_REQUIRED"


def test_attested_platform_identity_must_match_observed_machine():
    m = _module()
    result = m.evaluate_target_linux_reality(
        source_commit=SOURCE,
        observation=_observation(architecture="aarch64"),
        attestation_ref="attestation://target-linux/arch-mismatch",
        verifier=StaticVerifier("APPROVED_SELF_HOSTED_TARGET_LINUX", _attestation(architecture="x86_64")),
    )
    assert result["status"] == "FAIL"
    assert result["reason"] == "TARGET_LINUX_ATTESTATION_MACHINE_MISMATCH"
    assert result["target_linux_verified"] is False
