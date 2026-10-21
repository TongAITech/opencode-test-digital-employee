from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rc8_node.capabilities import CapabilityAdapterError, MavenJUnitCapabilityAdapter
from rc8_runtime import CapabilityState


def _fake_maven(tmp_path: Path, *, success: bool) -> str:
    """Create a directly executable fake Maven command on both CI platforms.

    Windows CreateProcess does not execute an extensionless bash script directly,
    so use a .cmd shim there. Linux keeps the executable bash script. This keeps
    the adapter test about a real subprocess rather than mocking subprocess.run.
    """
    if os.name == "nt":
        path = tmp_path / "mvn.cmd"
        if success:
            path.write_text("@echo off\r\necho Apache Maven RC8-test\r\nexit /b 0\r\n", encoding="utf-8")
        else:
            path.write_text("@echo off\r\necho broken maven 1>&2\r\nexit /b 9\r\n", encoding="utf-8")
    else:
        path = tmp_path / "mvn"
        if success:
            path.write_text("#!/usr/bin/env bash\necho 'Apache Maven RC8-test'\nexit 0\n", encoding="utf-8")
        else:
            path.write_text("#!/usr/bin/env bash\necho 'broken maven' >&2\nexit 9\n", encoding="utf-8")
        path.chmod(0o755)
    return str(path)


def test_successful_real_subprocess_probe_stays_probing_until_evidence_bound(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=True))
    result = adapter.probe()
    assert result.returncode == 0
    assert result.state == CapabilityState.PROBING
    assert "Apache Maven" in result.stdout
    evidence = Path(result.evidence_path)
    assert evidence.is_file()
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["probe_state"] == "PROBING"
    qualification = adapter.qualification_before_upload("node-1", result)
    assert qualification.state == CapabilityState.PROBING
    assert qualification.evidence_refs == []


def test_verified_requires_successful_probe_and_uploaded_artifact_reference(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=True))
    result = adapter.probe()
    verified = adapter.verified_qualification("node-1", result, "artifact-probe-1", verified_at=123)
    assert verified.state == CapabilityState.VERIFIED
    assert verified.evidence_refs == ["artifact-probe-1"]
    assert verified.verified_at == 123


def test_failed_tool_probe_is_degraded_and_cannot_be_verified(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=_fake_maven(tmp_path, success=False))
    result = adapter.probe()
    assert result.returncode == 9
    assert result.state == CapabilityState.DEGRADED
    with pytest.raises(CapabilityAdapterError, match="CAPABILITY_PROBE_NOT_SUCCESSFUL"):
        adapter.verified_qualification("node-1", result, "artifact-probe-1")


def test_missing_maven_is_unavailable_not_verified(tmp_path: Path) -> None:
    adapter = MavenJUnitCapabilityAdapter(str(tmp_path / "evidence"), maven_command=str(tmp_path / "missing-mvn"))
    result = adapter.probe()
    assert result.returncode is None
    assert result.state == CapabilityState.UNAVAILABLE
    qualification = adapter.qualification_before_upload("node-1", result)
    assert qualification.state == CapabilityState.UNAVAILABLE
