from __future__ import annotations

import json
import zipfile
from pathlib import Path

from rc7_release import plugin_payload


def _seed_vendor(root: Path) -> Path:
    vendor = root / "vendor"
    for name in plugin_payload.REQUIRED_PLUGIN_NAMES:
        target = plugin_payload.package_path(vendor, name)
        target.mkdir(parents=True, exist_ok=True)
        (target / "package.json").write_text(
            json.dumps({"name": name, "version": "test"}),
            encoding="utf-8",
        )
    return vendor


def test_inspect_vendor_requires_every_p0_plugin(tmp_path: Path) -> None:
    vendor = _seed_vendor(tmp_path)
    result = plugin_payload.inspect_vendor(vendor)
    assert result["status"] == "PASS"
    missing_target = plugin_payload.package_path(vendor, plugin_payload.REQUIRED_PLUGIN_NAMES[0])
    (missing_target / "package.json").unlink()
    result = plugin_payload.inspect_vendor(vendor)
    assert result["status"] == "FAIL"
    assert plugin_payload.REQUIRED_PLUGIN_NAMES[0] in result["missing"]


def test_materialize_payload_from_package_archive(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "package"
    vendor = _seed_vendor(tmp_path / "source")
    (vendor / "payload-manifest.json").write_text("{}\n", encoding="utf-8")
    archive = home / plugin_payload.PAYLOAD_ARCHIVE_RELATIVE
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(vendor.rglob("*")):
            if path.is_file():
                target.write(path, path.relative_to(vendor).as_posix())
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "state"))
    materialized = plugin_payload.materialize_payload(home)
    assert plugin_payload.inspect_vendor(materialized)["status"] == "PASS"
    assert materialized != vendor
    # A second call must reuse the immutable archive digest cache.
    assert plugin_payload.materialize_payload(home) == materialized
