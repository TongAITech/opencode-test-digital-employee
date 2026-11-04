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
            json.dumps({"name": name, "version": (
                plugin_payload.BSK_DSH_PLUGIN_VERSION
                if name == plugin_payload.BSK_DSH_PLUGIN_NAME else "test")}),
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


def test_bsk_plugin_archive_rejects_old_or_mismatched_version(tmp_path: Path) -> None:
    vendor = _seed_vendor(tmp_path)
    manifest_path = plugin_payload.package_path(
        vendor, plugin_payload.BSK_DSH_PLUGIN_NAME) / "package.json"
    manifest_path.write_text(json.dumps({
        "name": plugin_payload.BSK_DSH_PLUGIN_NAME, "version": "0.4.0"}))
    result = plugin_payload.inspect_vendor(vendor)
    assert result["status"] == "FAIL"
    assert plugin_payload.BSK_DSH_PLUGIN_NAME in result["missing"]


def test_bsk_plugin_cannot_override_bank_pinned_release(monkeypatch) -> None:
    import pytest

    monkeypatch.setenv(plugin_payload.SPEC_OVERRIDE_ENV, json.dumps({
        plugin_payload.BSK_DSH_PLUGIN_NAME:
            "@wxg-prc-cpg/browser-skill-dsh-plugin@latest"}))
    with pytest.raises(plugin_payload.PluginPayloadError, match="BSK_PLUGIN_VERSION_PIN_REQUIRED"):
        plugin_payload._resolved_specs()
    monkeypatch.delenv(plugin_payload.SPEC_OVERRIDE_ENV)
    specs = dict(plugin_payload._resolved_specs())
    assert specs[plugin_payload.BSK_DSH_PLUGIN_NAME].endswith("@0.4.1")
