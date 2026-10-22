import copy
import json
from pathlib import Path

import pytest

from scripts.rc8_validate_governance import ROOT, validate


MANIFEST = ROOT / "governance" / "rc8-capability-contracts.json"


def _payload():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write(tmp_path, payload):
    target = tmp_path / "claims.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def test_current_machine_governance_manifest_passes():
    result = validate(MANIFEST, ROOT)
    assert result["status"] == "PASS"
    assert result["claims"]["TOOL:MAVEN_JUNIT"] == "REALITY_VERIFIED"
    assert result["claims"]["LAYER:L1"] == "PARTIAL"
    assert result["claims"]["MISSION:RC8_FIRST_AUTONOMOUS_SLICE"] == "INSUFFICIENT"
    assert result["claims"]["RELEASE:RC8"] == "HOLD"


def test_tool_reality_cannot_drop_reality_gate(tmp_path):
    payload = _payload()
    row = next(item for item in payload["claims"] if item["claim_id"] == "TOOL:MAVEN_JUNIT")
    row["completed_gates"].remove("reality")
    with pytest.raises(ValueError, match="REALITY_VERIFIED_REQUIRES_REALITY_GATE"):
        validate(_write(tmp_path, payload), ROOT)


def test_partial_l1_cannot_be_silently_promoted_to_sufficient(tmp_path):
    payload = _payload()
    row = next(item for item in payload["claims"] if item["claim_id"] == "LAYER:L1")
    row["state"] = "SUFFICIENT"
    row["evaluator_ref"] = "fake-evaluator"
    row["evidence_refs"] = ["artifact:junit-green"]
    row["coverage_refs"] = ["coverage:fake"]
    row["unresolved_gap_ids"] = []
    # Required product/reality/coverage/sufficiency/regression gates remain incomplete.
    with pytest.raises(ValueError, match="SUFFICIENT_REQUIRES_SUFFICIENCY_GATE"):
        validate(_write(tmp_path, payload), ROOT)


def test_release_pass_cannot_depend_on_insufficient_mission(tmp_path):
    payload = _payload()
    release = next(item for item in payload["claims"] if item["claim_id"] == "RELEASE:RC8")
    release["state"] = "PASS"
    release["required_gates"] = ["mission_sufficient", "reality", "product", "deployment"]
    release["completed_gates"] = list(release["required_gates"])
    release["unresolved_gap_ids"] = []
    with pytest.raises(ValueError, match="RELEASE_PASS_REQUIRES_SUFFICIENT_MISSION_CLAIM"):
        validate(_write(tmp_path, payload), ROOT)


def test_claim_dependency_cannot_reference_missing_claim(tmp_path):
    payload = _payload()
    l1 = next(item for item in payload["claims"] if item["claim_id"] == "LAYER:L1")
    l1["dependency_claim_refs"].append("TOOL:JACOCO")
    with pytest.raises(ValueError, match="DEPENDENCY_CLAIM_NOT_FOUND"):
        validate(_write(tmp_path, payload), ROOT)


def test_frozen_contract_file_cannot_disappear(tmp_path):
    payload = _payload()
    payload["frozen_contract_refs"].append("docs/rc8/DOES-NOT-EXIST.md")
    with pytest.raises(ValueError, match="FROZEN_CONTRACT_MISSING"):
        validate(_write(tmp_path, payload), ROOT)
