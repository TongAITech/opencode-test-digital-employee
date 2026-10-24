from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_runtime.autonomous_contract_validator import (
    AutonomousContractValidationError,
    validate_shared_contract,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "autonomous_loop"


def test_repository_shared_contract_validates_fail_closed() -> None:
    result = validate_shared_contract(CONTRACT_ROOT)
    assert result.validated is True
    assert result.contract_id == "RC-AUTONOMOUS-TEST-LOOP"
    assert result.contract_version == "1.0.0"
    assert result.baseline_sha == "98d7ee59cb3caf760177d7aaa933ee70082a6ff3"
    assert len(result.schema_files) == 5


def test_validator_rejects_bank_field_reality_overstatement(tmp_path: Path) -> None:
    target = tmp_path / "autonomous_loop"
    import shutil
    shutil.copytree(CONTRACT_ROOT, target)
    manifest_path = target / "contract_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reality_status"]["bank_field_reality"] = "PASS"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AutonomousContractValidationError, match="CONTRACT_REALITY_BOUNDARY_DRIFT"):
        validate_shared_contract(target)


def test_validator_rejects_layer_taxonomy_drift(tmp_path: Path) -> None:
    target = tmp_path / "autonomous_loop"
    import shutil
    shutil.copytree(CONTRACT_ROOT, target)
    layers_path = target / "canonical_layers.json"
    rows = json.loads(layers_path.read_text(encoding="utf-8"))
    rows[4]["name"] = "API_CONTRACT"
    layers_path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(AutonomousContractValidationError, match="CANONICAL_LAYER_MEANING_DRIFT"):
        validate_shared_contract(target)
