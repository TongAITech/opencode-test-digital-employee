from __future__ import annotations

from pathlib import Path

import pytest

import rc7_release.runtime_build_bootstrap as bootstrap


def test_ripgrep_bootstrap_selects_exact_windows_x64_asset_and_writes_github_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tag = "99.8.7"
    asset_name = "ripgrep-%s-x86_64-pc-windows-msvc.zip" % tag
    digest = "a" * 64
    monkeypatch.setattr(
        bootstrap,
        "_request_json",
        lambda url: {
            "tag_name": tag,
            "assets": [
                {
                    "name": asset_name,
                    "digest": "sha256:" + digest,
                    "browser_download_url": "https://example.invalid/rg.zip",
                },
                {
                    "name": asset_name + ".sha256",
                    "digest": "sha256:" + "b" * 64,
                    "browser_download_url": "https://example.invalid/rg.zip.sha256",
                },
            ],
        },
    )

    def fake_download(url: str, destination: Path, expected: str) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"zip")
        assert url.endswith("rg.zip")
        assert expected == "sha256:" + digest
        return digest

    def fake_extract(archive: Path, destination: Path) -> None:
        binary = destination / ("ripgrep-%s-x86_64-pc-windows-msvc" % tag) / "rg.exe"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"rg")

    class Proc:
        returncode = 0
        stdout = b"ripgrep 99.8.7\n"

    monkeypatch.setattr(bootstrap, "_download", fake_download)
    monkeypatch.setattr(bootstrap, "_safe_extract", fake_extract)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: Proc())

    github_path = tmp_path / "github-path.txt"
    result = bootstrap.acquire_ripgrep(tmp_path / "runtime", github_path)

    assert result["status"] == "PASS"
    assert result["resolved_version"] == tag
    assert result["asset"] == asset_name
    assert result["sha256"] == digest
    assert Path(result["binary"]).name == "rg.exe"
    assert github_path.read_text(encoding="utf-8").strip() == str(Path(result["binary"]).parent)


def test_ripgrep_bootstrap_rejects_asset_without_upstream_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tag = "1.2.3"
    name = "ripgrep-%s-x86_64-pc-windows-msvc.zip" % tag
    monkeypatch.setattr(
        bootstrap,
        "_request_json",
        lambda url: {
            "tag_name": tag,
            "assets": [
                {
                    "name": name,
                    "digest": None,
                    "browser_download_url": "https://example.invalid/rg.zip",
                }
            ],
        },
    )

    with pytest.raises(bootstrap.RuntimeBuildBootstrapError, match="RIPGREP_RELEASE_DIGEST_REQUIRED"):
        bootstrap.acquire_ripgrep(tmp_path / "runtime")


def test_ripgrep_bootstrap_rejects_wrong_architecture_only_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_request_json",
        lambda url: {
            "tag_name": "1.2.3",
            "assets": [
                {
                    "name": "ripgrep-1.2.3-aarch64-pc-windows-msvc.zip",
                    "digest": "sha256:" + "c" * 64,
                    "browser_download_url": "https://example.invalid/arm.zip",
                }
            ],
        },
    )

    with pytest.raises(bootstrap.RuntimeBuildBootstrapError, match="RIPGREP_WINDOWS_X64_ASSET_NOT_UNIQUE"):
        bootstrap.acquire_ripgrep(tmp_path / "runtime")
