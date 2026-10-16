from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rc7_launchers_bind_real_junit_execution_to_portable_offline_maven() -> None:
    cmd = (ROOT / "packaging" / "rc7" / "AITEST.cmd").read_text(encoding="utf-8")
    sh = (ROOT / "packaging" / "rc7" / "AITEST.sh").read_text(encoding="utf-8")
    settings = (ROOT / "packaging" / "rc7" / "maven-offline-settings.xml").read_text(encoding="utf-8")

    for text in (cmd, sh):
        assert "PFC_MAVEN_REPO" in text
        assert "PFC_MAVEN_SETTINGS" in text
        assert "MAVEN_ARGS" in text
        assert "maven.legacyLocalRepo=true" in text
        assert "maven-repository" in text
        assert "maven-offline-settings.xml" in text
    assert "<offline>true</offline>" in settings
    assert "<mirror>" not in settings
