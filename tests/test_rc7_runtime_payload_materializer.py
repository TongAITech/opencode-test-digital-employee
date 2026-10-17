from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import rc7_release.runtime_payload_materializer as materializer
from rc7_release.package import PACKAGE_LOCAL_BROWSER, PACKAGE_LOCAL_CODEGRAPH


def test_release_asset_requires_one_sha256_backed_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        materializer,
        "_request_json",
        lambda url: {
            "tag_name": "v9.9.9",
            "assets": [
                {"name": "tool-linux.zip", "digest": "sha256:" + "1" * 64, "browser_download_url": "https://example/linux"},
                {"name": "tool-windows-amd64.zip", "digest": "sha256:" + "2" * 64, "browser_download_url": "https://example/windows"},
            ],
        },
    )
    release, asset = materializer._release_asset("owner/repo", contains=("windows-amd64", ".zip"))
    assert release["tag_name"] == "v9.9.9"
    assert asset["name"] == "tool-windows-amd64.zip"


def test_release_asset_without_upstream_digest_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        materializer,
        "_request_json",
        lambda url: {"assets": [{"name": "tool.zip", "digest": None, "browser_download_url": "https://example/tool"}]},
    )
    with pytest.raises(materializer.RuntimePayloadMaterializerError, match="RELEASE_ASSET_DIGEST_REQUIRED"):
        materializer._release_asset("owner/repo", name="tool.zip")


def test_safe_extract_rejects_zip_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("../escape.txt", "no")
    with pytest.raises(materializer.RuntimePayloadMaterializerError, match="UNSAFE_RUNTIME_ARCHIVE_PATH"):
        materializer._safe_extract(archive, tmp_path / "out")


def test_manifest_update_marks_codegraph_browser_bundled_but_not_delivery_complete(tmp_path: Path) -> None:
    manifest = {
        "package_local_codegraph": {"path": PACKAGE_LOCAL_CODEGRAPH.as_posix(), "bundled": False},
        "package_local_browser": {"path": PACKAGE_LOCAL_BROWSER.as_posix(), "bundled": False},
    }
    (tmp_path / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        {"payload": "codegraph", "resolved_version": "v1", "sha256": "a" * 64},
        {"payload": "controlled_browser", "resolved_version": "v2", "sha256": "b" * 64},
    ]
    materializer._update_manifest(tmp_path, rows)
    updated = json.loads((tmp_path / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    assert updated["package_local_codegraph"]["bundled"] is True
    assert updated["package_local_browser"]["bundled"] is True
    assert updated["package_local_codegraph"]["sha256"] == "a" * 64
    assert updated["package_local_browser"]["sha256"] == "b" * 64
    assert updated["delivery_runtime_complete"] is False
    assert updated["runtime_payload_inventory"] == materializer.INVENTORY_FILE


def test_materializer_refuses_non_windows_host(tmp_path: Path) -> None:
    if materializer.os.name == "nt":
        pytest.skip("non-Windows contract")
    with pytest.raises(materializer.RuntimePayloadMaterializerError, match="WINDOWS_RUNTIME_MATERIALIZER_REQUIRES_WINDOWS"):
        materializer.materialize(tmp_path)
