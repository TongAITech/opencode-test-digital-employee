from __future__ import annotations

import json
from pathlib import Path

from rc7_runtime.bank_field_services import REQUIRED_CAPABILITIES


def test_bank_service_probe_entrypoints_and_provider_template_are_bundled():
    repo = Path(__file__).resolve().parents[1]
    sh = (repo / "packaging" / "rc7" / "QUALIFY-BANK-SERVICES.sh").read_text(encoding="utf-8")
    cmd = (repo / "packaging" / "rc7" / "QUALIFY-BANK-SERVICES.cmd").read_text(encoding="utf-8")
    final_sh = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.sh").read_text(encoding="utf-8")
    final_cmd = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.cmd").read_text(encoding="utf-8")
    template = json.loads((repo / "packaging" / "rc7" / "bank-field-providers.example.json").read_text(encoding="utf-8"))

    for text in (sh, cmd):
        assert "rc7_runtime.bank_field_services probe" in text
        assert "approve-db-write" in text
        assert "PFC_RC7_BANK_TARGET_ID" in text
        assert "PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG" in text
    for text in (final_sh, final_cmd):
        assert "rc7_runtime.bank_field_services qualify" in text
        assert "rc7-bank-service-qualification.json" in text
        assert "PFC_RC7_BANK_TARGET_ID" in text
        assert "--require-pass" in text

    assert set(template["providers"]) == set(REQUIRED_CAPABILITIES)
    assert "BANK_DB_WRITE" in template["provider_response_contract"]
    assert "cleanup_ref_or_rollback_ref" in template["provider_response_contract"]["BANK_DB_WRITE"]
