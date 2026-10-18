from __future__ import annotations

import json
from pathlib import Path

from rc7_admin.requirement_hierarchy import RequirementHierarchyView
from rc7_release import optional_enhancements
from rc7_release.vision_capability import probe as probe_vision


class FakeTruth:
    def __init__(self):
        self.rows = [{
            "id": "RA-1", "release_id": "BLOAN-PF1.2.0", "requirement_id": "STBB19-320", "status": "PASS", "artifact_version": 2,
            "brs": [{"id": "BR-1", "title": "业务规则", "srs": [{"id": "SR-1", "title": "系统规则", "trs": [{"id": "TR-1", "title": "技术约束"}]}]}],
        }]
    def rebuild_projection(self): return None
    def query(self, artifact_type, **filters): return self.rows if artifact_type == "requirement_analysis" else []


def _write_plugin(root: Path, name: str) -> None:
    path = optional_enhancements.package_path(root, name); path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(json.dumps({"name": name, "version": "test"}), encoding="utf-8")


def test_requirement_hierarchy_projects_br_sr_tr_without_second_truth_store() -> None:
    result = RequirementHierarchyView(FakeTruth()).list(page=1, page_size=20, filters={"version": "1.2.0"})
    assert result["total"] == 3
    rows = {row["node_id"]: row for row in result["items"]}
    assert set(row["level"] for row in result["items"]) == {"BR", "SR", "TR"}
    assert rows["SR-1"]["parent_id"] == "BR-1"
    assert rows["TR-1"]["parent_id"] == "SR-1"


def test_optional_probe_never_hides_required_dsh_payload_blocker(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"; state = tmp_path / "state"; monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    _write_plugin(state / "plugin-runtime" / "optional-enhancements", "dsh-vision-router")
    result = optional_enhancements.probe(home)
    assert result["status"] == "FAIL"
    assert result["required_dsh_payload"] == "FAIL"
    assert "dsh-vision-router" in result["available_optional"]
    assert result["public_registry_forbidden_on_bank_host"] is True


def test_vision_prefers_local_ocr_until_router_is_actually_active(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"; marker = home / "workspace-template/runtime/python/.rc7-capabilities/local_ocr_cv.json"
    marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text('{"status":"PASS"}\n', encoding="utf-8")
    state = tmp_path / "state"; monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state)); _write_plugin(state / "plugin-runtime" / "optional-enhancements", "dsh-vision-router")
    monkeypatch.delenv("PFC_RC7_VISION_ROUTER_ACTIVE", raising=False); monkeypatch.delenv("PFC_BANK_VLM_ENDPOINT", raising=False); monkeypatch.delenv("PFC_BANK_VLM_APPROVED", raising=False)
    result = probe_vision(home)
    assert result["status"] == "PASS"
    assert result["selected_provider"] == "LOCAL_OCR_CV"
    assert result["dsh_vision_router"]["available"] is True
    assert result["dsh_vision_router"]["active"] is False
    assert result["public_remote_image_upload"] is False


def test_repository_release_metadata_has_no_stale_wave2_candidate() -> None:
    root = Path(__file__).resolve().parents[1]; data = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")); text = json.dumps(data, sort_keys=True)
    assert data["status"] == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
    assert data["construction_branch"] == "work/rc7-field-hardening"
    assert data["source_commit_resolution"] == "RESOLVE_CURRENT_GIT_HEAD_AT_PACKAGE_BUILD"
    assert "repair/g3-g4-wave2" not in text
    assert "884947012a7c7735f11708734f1955ee552cf1fe" not in text
    assert data["turnkey_delivery"]["required_runtime_payload_count"] == 16
    assert data["release_invariants"]["bank_final_requires_real_bank_mission"] is True
