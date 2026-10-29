from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_release.rc72_platform_qualification import (
    QualificationKind,
    build_source_platform_evidence,
    main,
)


def test_windows_engineering_evidence_is_never_field_or_bank_final() -> None:
    evidence = build_source_platform_evidence(
        qualification_kind=QualificationKind.WINDOWS_ENGINEERING,
        source_commit="abc123",
        platform_family="Windows",
        platform_release="test",
        architecture="AMD64",
        python_version="3.8.10",
    )

    assert evidence["schema"] == "pfc.aitest.rc7.2.platform-source-baseline.v1"
    assert evidence["qualification_kind"] == "WINDOWS_ENGINEERING"
    assert evidence["source_commit"] == "abc123"
    assert evidence["status"] == "PASS"
    assert evidence["field_verified"] is False
    assert evidence["bank_final"] is False
    assert evidence["target_linux_verified"] is False


def test_linux_engineering_proxy_cannot_claim_target_linux() -> None:
    evidence = build_source_platform_evidence(
        qualification_kind=QualificationKind.LINUX_ENGINEERING_PROXY,
        source_commit="def456",
        platform_family="Linux",
        platform_release="ubuntu-runner",
        architecture="x86_64",
        python_version="3.8.18",
    )

    assert evidence["qualification_kind"] == "LINUX_ENGINEERING_PROXY"
    assert evidence["target_linux_verified"] is False
    assert "not target Linux" in " ".join(evidence["notes"])


def test_evidence_rejects_blank_source_commit() -> None:
    with pytest.raises(ValueError, match="source_commit"):
        build_source_platform_evidence(
            qualification_kind=QualificationKind.WINDOWS_ENGINEERING,
            source_commit=" ",
            platform_family="Windows",
            platform_release="test",
            architecture="AMD64",
            python_version="3.8.10",
        )


def test_cli_writes_structured_evidence(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"

    rc = main(
        [
            "--qualification-kind",
            "LINUX_ENGINEERING_PROXY",
            "--source-commit",
            "sha789",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["qualification_id"].startswith("Q1-")
    assert payload["qualification_kind"] == "LINUX_ENGINEERING_PROXY"
    assert payload["source_commit"] == "sha789"
    assert payload["field_verified"] is False
    assert payload["bank_final"] is False
