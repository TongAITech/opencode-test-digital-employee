from __future__ import annotations

import json
from pathlib import Path


REQUIRED_CASE_PROVIDER_CAPABILITIES = {
    "PRECONDITION_ENVIRONMENT",
    "PRECONDITION_AUTH",
    "PRECONDITION_BUSINESS_STATE",
    "PRECONDITION_DATA",
    "PRECONDITION_DEPENDENCY",
    "DATA_REUSE_EXISTING",
    "DATA_DERIVE",
    "DATA_API_CREATE",
    "DATA_UI_CREATE",
    "DATA_DB_CREATE",
    "DATA_FIXTURE",
    "DATA_MOCK",
    "DATA_VERIFY",
}


def test_packaged_case_provider_example_matches_case_preparation_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "packaging" / "rc7" / "bank-field-providers.example.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "pfc.aitest.rc7.case-provider.example.v2"
    providers = payload["providers"]
    assert REQUIRED_CASE_PROVIDER_CAPABILITIES.issubset(set(providers))
    for capability in REQUIRED_CASE_PROVIDER_CAPABILITIES:
        command = providers[capability]["command"]
        assert command[:2] == ["python", "PATH_TO_BANK_CASE_PROVIDER.py"]
        assert len(command) == 3
    notes = "\n".join(payload.get("notes") or [])
    assert "state/bank-field-providers.json" in notes
    assert "foura_auth.py" in notes
    assert "historical cookie fallback is forbidden" in notes


def test_bank_mission_launchers_bind_only_real_canonical_case_provider_config() -> None:
    root = Path(__file__).resolve().parents[1]
    cmd = (root / "packaging" / "rc7" / "START-RC7-BANK-MISSION.cmd").read_text(encoding="utf-8")
    sh = (root / "packaging" / "rc7" / "START-RC7-BANK-MISSION.sh").read_text(encoding="utf-8")

    assert "PFC_RC7_CASE_PROVIDER_CONFIG" in cmd
    assert "%ROOT%\\state\\bank-field-providers.json" in cmd
    assert 'set "PFC_RC7_CASE_PROVIDER_CONFIG=%PFC_RC7_CASE_PROVIDER_CANONICAL%"' in cmd
    assert "CASE_PROVIDER_CONFIG_NOT_FOUND" in cmd
    assert "FIELD_REQUIRED" in cmd

    assert "PFC_RC7_CASE_PROVIDER_CONFIG" in sh
    assert '$ROOT/state/bank-field-providers.json' in sh
    assert 'export PFC_RC7_CASE_PROVIDER_CONFIG' in sh
    assert "CASE_PROVIDER_CONFIG_NOT_FOUND" in sh
    assert "FIELD_REQUIRED" in sh

    # The example may be mentioned as the source template, but must never be
    # assigned as the runtime provider config itself.
    assert "PFC_RC7_CASE_PROVIDER_CONFIG=%ROOT%\\packaging\\rc7\\bank-field-providers.example.json" not in cmd
    assert 'PFC_RC7_CASE_PROVIDER_CONFIG="$ROOT/packaging/rc7/bank-field-providers.example.json"' not in sh
