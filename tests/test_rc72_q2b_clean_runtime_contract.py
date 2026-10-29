from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

from rc7_release import windows_clean_qualification as legacy_clean


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_clean_qualifier_exposes_parameterized_contract_without_changing_default_entrypoint():
    assert hasattr(legacy_clean, "qualify")
    assert hasattr(legacy_clean, "qualify_with_contract"), "Q2-B requires reusable clean qualifier contract"
    signature = inspect.signature(legacy_clean.qualify_with_contract)
    for name in (
        "package_verifier",
        "qualification_name",
        "mission_prefix",
        "release_prefix",
        "goal",
    ):
        assert name in signature.parameters


def test_rc72_clean_qualification_wrapper_exists_and_is_distinct_from_rc7_identity():
    module = importlib.import_module("rc7_release.rc72_windows_clean_qualification")
    assert module.QUALIFICATION_NAME == "RC72_WINDOWS_CLEAN_PACKAGE"
    assert module.RELEASE_FAMILY == "RC7.2"
    assert module.BUSINESS_ROOT == "RELEASE_BATCH"


def test_rc72_clean_qualification_wrapper_delegates_to_parameterized_legacy_core(monkeypatch, tmp_path):
    module = importlib.import_module("rc7_release.rc72_windows_clean_qualification")
    observed = {}

    def fake_core(package_root, **kwargs):
        observed["root"] = Path(package_root)
        observed.update(kwargs)
        return {
            "status": "PASS",
            "qualification": kwargs["qualification_name"],
            "source_commit": "a" * 40,
            "real_mission_pass": False,
            "bank_field_pass": False,
        }

    monkeypatch.setattr(module, "qualify_with_contract", fake_core)
    result = module.qualify(tmp_path)

    assert observed["root"] == tmp_path
    assert observed["qualification_name"] == "RC72_WINDOWS_CLEAN_PACKAGE"
    assert observed["mission_prefix"] == "RC72-WINDOWS-CLEAN"
    assert observed["release_prefix"] == "RC72-CLEAN-TRANSPORT"
    assert observed["package_verifier"] is module.verify_rc72_package
    assert result["release_family"] == "RC7.2"
    assert result["business_root"] == "RELEASE_BATCH"
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["real_mission_pass"] is False
    assert result["bank_field_pass"] is False


def test_rc72_git_bash_entrypoint_is_thin_verify_then_delegate_wrapper():
    launcher = REPO_ROOT / "packaging" / "rc7.2" / "AITEST.sh"
    assert launcher.is_file(), "RC7.2 Git Bash launcher missing"
    text = launcher.read_text(encoding="utf-8")

    verify_pos = text.find("rc7_release.rc72_package verify")
    delegate_pos = text.find("packaging/rc7/AITEST.sh")
    assert verify_pos >= 0
    assert delegate_pos > verify_pos
    assert "PFC_RC7_SKIP_QUALIFY=1" in text
    assert "rc7.2-bank" in text
    assert "dsh plugin add" not in text
    assert "pip install" not in text
    assert "npm install" not in text


def test_rc72_package_contract_requires_q2b_runtime_and_launcher_files():
    module = importlib.import_module("rc7_release.rc72_package")
    required = set(module.RC72_Q2B_REQUIRED_FILES)
    assert "rc7_release/rc72_windows_clean_qualification.py" in required
    assert "packaging/rc7.2/AITEST.sh" in required


def test_q2b_wrapper_cannot_claim_field_or_bank_final(monkeypatch, tmp_path):
    module = importlib.import_module("rc7_release.rc72_windows_clean_qualification")

    def fake_core(_root, **kwargs):
        return {
            "status": "PASS",
            "qualification": kwargs["qualification_name"],
            "source_commit": "b" * 40,
            "real_mission_pass": False,
            "bank_field_pass": False,
        }

    monkeypatch.setattr(module, "qualify_with_contract", fake_core)
    result = module.qualify(tmp_path)
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert result["target_linux_verified"] is False
