from __future__ import annotations

from pathlib import Path

from rc7_release.rc71_identity import (
    BASELINE_COMMIT,
    BUILD_STATUS,
    REQUIRED_HARDENING_FILES,
    identity,
    validate_hardening_payload,
)


EXPECTED_BASELINE = "ef7052e42485d060c1dc7e0ec9517c59df4e2ae5"


def test_rc71_identity_freezes_current_hardening_without_claiming_bank_final() -> None:
    payload = identity("f" * 40)
    assert BASELINE_COMMIT == EXPECTED_BASELINE
    assert payload["baseline_rc7_commit"] == EXPECTED_BASELINE
    assert payload["build_status"] == BUILD_STATUS == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
    assert payload["claims"]["bank_final"] is False
    assert payload["hardening_contract"]["bank_field_reality"] == "NOT_VERIFIED"
    assert payload["hardening_contract"]["engineering_fixture_bank_field_authority"] is False
    assert payload["hardening_contract"]["bank_field_requires_positive_runtime_provenance"] is True
    assert payload["hardening_contract"]["second_start_idempotence_required"] is True
    assert "BANK_FIELD_REALITY_FAIL_CLOSED_PROVENANCE_GATE" in payload["fixes"]
    assert "ENGINEERING_FIXTURE_ISOLATED_FROM_BANK_FIELD_REALITY" in payload["fixes"]
    assert "TURNKEY_SECOND_START_IDEMPOTENCE_GATE" in payload["fixes"]


def test_rc71_identity_rejects_package_missing_reality_hardening(tmp_path: Path) -> None:
    result = validate_hardening_payload(str(tmp_path))
    assert result["status"] == "HOLD"
    assert set(result["missing_files"]) == set(REQUIRED_HARDENING_FILES)
    assert result["bank_field_reality"] == "NOT_VERIFIED"


def test_rc71_identity_accepts_package_containing_required_hardening(tmp_path: Path) -> None:
    for relative in REQUIRED_HARDENING_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("hardening\n", encoding="utf-8")
    result = validate_hardening_payload(str(tmp_path))
    assert result["status"] == "PASS"
    assert result["missing_files"] == []


def test_turnkey_workflow_builds_current_branch_and_requires_second_start() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/rc7.1-turnkey.yml").read_text(encoding="utf-8")
    assert "work/rc7.1-minimal-hardening" in workflow
    assert "RC7.1 second-start idempotence gate" in workflow
    assert "rc71-second-start-recovery.json" in workflow
    assert "second_start='PASS'" in workflow
    assert EXPECTED_BASELINE in workflow
    assert "ac890eebeae96c9704d777e5ba8cac428f7a25b8" not in workflow
