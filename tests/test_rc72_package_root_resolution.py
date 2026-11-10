from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_release.rc72_package_root import (
    PackageRootResolutionError,
    resolve_package_root,
)


def _package(root: Path, source: str = "a" * 40) -> Path:
    (root / "workspace-template/runtime/python").mkdir(parents=True)
    (root / "packaging/rc7.2").mkdir(parents=True)
    (root / "SOURCE_COMMIT").write_text(source + "\n", encoding="utf-8")
    (root / "PACKAGE_MANIFEST.json").write_text(
        json.dumps({"source_commit": source}), encoding="utf-8"
    )
    (root / "RC72_RELEASE_IDENTITY.json").write_text(
        json.dumps({"source_commit": source}), encoding="utf-8"
    )
    (root / "workspace-template/runtime/python/python.exe").write_bytes(b"test")
    (root / "packaging/rc7.2/AITEST.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return root


def test_exact_package_root_is_preserved(tmp_path: Path) -> None:
    root = _package(tmp_path / "package")
    assert resolve_package_root(root) == root.resolve()


def test_launcher_file_and_nested_launcher_directory_resolve_to_inner_root(tmp_path: Path) -> None:
    root = _package(tmp_path / "outer" / "inner")
    assert resolve_package_root(root / "packaging/rc7.2/AITEST.sh") == root.resolve()
    assert resolve_package_root(root / "packaging/rc7.2") == root.resolve()


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_outer_extract_directory_resolves_single_nested_package(tmp_path: Path, depth: int) -> None:
    outer = tmp_path / "extract destination with spaces"
    nested = outer
    for index in range(depth):
        nested = nested / ("folder %d" % index)
    root = _package(nested / "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10")
    assert resolve_package_root(outer) == root.resolve()


def test_ambiguous_nested_packages_fail_closed(tmp_path: Path) -> None:
    outer = tmp_path / "extract"
    _package(outer / "one")
    _package(outer / "two")
    with pytest.raises(PackageRootResolutionError, match="RC72_PACKAGE_ROOT_AMBIGUOUS"):
        resolve_package_root(outer)


def test_mismatched_identity_is_not_accepted_as_package_root(tmp_path: Path) -> None:
    root = _package(tmp_path / "package")
    (root / "RC72_RELEASE_IDENTITY.json").write_text(
        json.dumps({"source_commit": "b" * 40}), encoding="utf-8"
    )
    with pytest.raises(PackageRootResolutionError, match="RC72_PACKAGE_ROOT_NOT_FOUND"):
        resolve_package_root(root)


def test_symlinked_required_marker_is_rejected(tmp_path: Path) -> None:
    root = _package(tmp_path / "package")
    source = root / "SOURCE_COMMIT"
    real = root / "SOURCE_COMMIT.real"
    source.rename(real)
    try:
        source.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are not available on this runner")
    with pytest.raises(PackageRootResolutionError, match="RC72_PACKAGE_ROOT_NOT_FOUND"):
        resolve_package_root(root)
