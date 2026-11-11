"""Fail-closed acceptance of reused native offline addon payload extraction."""
import hashlib
import json
import zipfile

import pytest

from rc7_release.rc72_native_additional_plugins import (
    ARCHIVE_REL, MANIFEST_REL, PINNED_PACKAGES, SCHEMA, AdditionalPluginError,
    verify_extracted,
)


def _fixture(tmp_path):
    archive = tmp_path / ARCHIVE_REL
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
        for name, version, license_name in PINNED_PACKAGES:
            row = {"name": name, "version": version}
            if name != "graph-memory":  # pinned upstream package.json omits license
                row["license"] = license_name
            base = "node_modules/" + name + "/"
            out.writestr(base + "package.json", json.dumps(row))
            out.writestr(base + "LICENSE", "MIT License\nPermission is hereby granted, free of charge\n")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = tmp_path / MANIFEST_REL
    manifest.write_text(json.dumps({
        "schema": SCHEMA, "status": "PASS", "all_required_bundled": True,
        "required_count": len(PINNED_PACKAGES), "archive_sha256": sha,
    }), encoding="utf-8")
    dest = tmp_path / "runtime" / "dsh-additions"
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        source.extractall(dest)
    (dest / ".verified-source.sha256").write_text(sha + "\n", encoding="utf-8")
    return dest


def test_native_addon_cache_exact_match_passes_only_source_gate(tmp_path):
    dest = _fixture(tmp_path)
    actual = verify_extracted(tmp_path, dest)
    assert actual["status"] == "PASS"
    assert actual["scope"] == "LOCAL_EXTRACTED_SOURCE_ONLY"
    assert actual["plugin_count"] == 5


def test_native_addon_cache_changed_bytes_fail_closed(tmp_path):
    dest = _fixture(tmp_path)
    (dest / "node_modules/graph-memory/package.json").write_text("{}")
    with pytest.raises(AdditionalPluginError, match="EXTRACTED_.*CHANGED|EXTRACTED_CONTENT_MISMATCH"):
        verify_extracted(tmp_path, dest)


def test_native_addon_cache_stale_marker_fail_closed(tmp_path):
    dest = _fixture(tmp_path)
    (dest / ".verified-source.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(AdditionalPluginError, match="MARKER_MISMATCH"):
        verify_extracted(tmp_path, dest)


def test_native_addon_cache_extra_file_fail_closed(tmp_path):
    dest = _fixture(tmp_path)
    (dest / "unaudited.js").write_text("console.log('unexpected')")
    with pytest.raises(AdditionalPluginError, match="FILESET_MISMATCH"):
        verify_extracted(tmp_path, dest)


def test_native_addon_cache_missing_plugin_file_fail_closed(tmp_path):
    dest = _fixture(tmp_path)
    (dest / "node_modules/graph-memory/package.json").unlink()
    with pytest.raises(AdditionalPluginError, match="EXTRACTED_MISSING_OR_CHANGED"):
        verify_extracted(tmp_path, dest)
