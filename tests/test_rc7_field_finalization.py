from __future__ import annotations

import json
import zipfile
from pathlib import Path

from rc7_admin.requirement_hierarchy import RequirementHierarchyView
from rc7_release import optional_enhancements, optional_plugin_payload
from rc7_release.optional_plugin_payload import PAYLOAD_ARCHIVE_RELATIVE
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


def test_bundled_optional_payload_is_materialized_without_bank_network(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"; state = tmp_path / "state"; monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    archive = home / PAYLOAD_ARCHIVE_RELATIVE; archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        target.writestr("node_modules/dsh-vision-router/package.json", json.dumps({"name": "dsh-vision-router", "version": "bundled-test"}))
        target.writestr("payload-manifest.json", json.dumps({"status": "PARTIAL", "bundled": ["dsh-vision-router"]}))
    result = optional_enhancements.probe(home)
    row = result["plugins"]["dsh-vision-router"]
    assert row["available"] is True
    assert row["source"] == "PACKAGE_VENDOR_ARCHIVE"
    assert row["version"] == "bundled-test"
    assert result["bundled_optional_payload"]["materialized"] is True
    assert not result["registry_configured"]


def test_optional_acquire_rejects_public_registry_even_when_approved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PFC_NPM_REGISTRY_URL", "https://registry.npmjs.org")
    monkeypatch.setenv("PFC_NPM_REGISTRY_APPROVED", "1")
    result = optional_enhancements.acquire(tmp_path, ["dsh-vision-router"])
    assert result["status"] == "FAIL"
    assert result["reason"] == "PUBLIC_NPM_REGISTRY_FORBIDDEN"


def test_vision_prefers_local_ocr_until_dsh_activation_is_proven(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"; marker = home / "workspace-template/runtime/python/.rc7-capabilities/local_ocr_cv.json"
    marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text('{"status":"PASS"}\n', encoding="utf-8")
    state = tmp_path / "state"; monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state)); _write_plugin(state / "plugin-runtime" / "optional-enhancements", "dsh-vision-router")
    monkeypatch.setenv("PFC_RC7_VISION_ROUTER_ACTIVE", "1")
    monkeypatch.delenv("PFC_BANK_VLM_ENDPOINT", raising=False); monkeypatch.delenv("PFC_BANK_VLM_APPROVED", raising=False)
    result = probe_vision(home)
    assert result["status"] == "PASS"
    assert result["selected_provider"] == "LOCAL_OCR_CV"
    assert result["dsh_vision_router"]["available"] is True
    assert result["dsh_vision_router"]["active"] is False
    assert result["dsh_vision_router"]["activation_authority"] == "DSH_PROFILE_ACTIVATION_RECEIPT"
    assert result["public_remote_image_upload"] is False


def test_vision_selects_dsh_only_after_activation_receipt(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"; state = tmp_path / "state"; monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state)); monkeypatch.setenv("PFC_RC7_DSH_PROFILE", "rc7-field")
    _write_plugin(state / "plugin-runtime" / "optional-enhancements", "dsh-vision-router")
    receipt = optional_enhancements.activation_receipt_path(home, "rc7-field", "dsh-vision-router")
    receipt.parent.mkdir(parents=True, exist_ok=True); receipt.write_text(json.dumps({"status": "ACTIVE", "plugin": "dsh-vision-router", "profile": "rc7-field"}), encoding="utf-8")
    result = probe_vision(home)
    assert result["status"] == "PASS"
    assert result["selected_provider"] == "DSH_VISION_ROUTER"
    assert result["dsh_vision_router"]["active"] is True


def test_anydoc_uses_github_build_source_and_canonical_admin_is_product_surface() -> None:
    specs = dict(optional_plugin_payload.OPTIONAL_PLUGIN_SPECS)
    assert specs["dsh-plugin-anydoc"] == "github:beancookie/dsh-plugin-anydoc#main"
    root = Path(__file__).resolve().parents[1]
    entry = (root / "rc7_admin" / "__main__.py").read_text(encoding="utf-8")
    assert "from .product_server import main" in entry


def test_repository_release_metadata_has_no_stale_wave2_candidate() -> None:
    root = Path(__file__).resolve().parents[1]; data = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")); text = json.dumps(data, sort_keys=True)
    assert data["status"] == "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
    assert data["construction_branch"] == "work/rc7-field-hardening"
    assert data["source_commit_resolution"] == "RESOLVE_CURRENT_GIT_HEAD_AT_PACKAGE_BUILD"
    assert "repair/g3-g4-wave2" not in text
    assert "884947012a7c7735f11708734f1955ee552cf1fe" not in text
    assert data["turnkey_delivery"]["required_runtime_payload_count"] == 16
    assert data["turnkey_delivery"]["dsh_optional_plugin_target_count"] == 4
    assert data["turnkey_delivery"]["dsh_optional_plugins_turnkey_bundle_required"] is True
    assert data["turnkey_delivery"]["dsh_optional_plugins_activation_optional"] is True
    assert data["turnkey_delivery"]["dsh_error_handling_model"] == "BUILTIN_DSH_SKILL_NOT_NPM_PLUGIN"
    assert data["turnkey_delivery"]["canonical_admin_launcher_uses_product_surface"] is True
    assert data["turnkey_delivery"]["optional_plugin_explicit_enable_fails_closed_when_unavailable"] is True
    assert data["release_invariants"]["bank_final_requires_real_bank_mission"] is True
