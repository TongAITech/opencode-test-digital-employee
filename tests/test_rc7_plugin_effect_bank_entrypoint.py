from __future__ import annotations

from pathlib import Path


def test_bank_final_runs_plugin_effect_gate_before_final_qualification():
    repo = Path(__file__).resolve().parents[1]
    sh = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.sh").read_text(encoding="utf-8")
    cmd = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.cmd").read_text(encoding="utf-8")
    for text in (sh, cmd):
        assert "PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE" in text
        assert "rc7_release.plugin_effect_qualification" in text
        assert "rc7-dsh-runtime-profile.json" in text
        assert "rc7-plugin-effect-qualification.json" in text
        assert "--require-pass" in text
