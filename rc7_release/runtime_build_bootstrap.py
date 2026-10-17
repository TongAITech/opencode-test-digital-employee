from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


SCHEMA_VERSION = "pfc.aitest.rc7.runtime-build-bootstrap.v1"
USER_AGENT = "PFC-AITest-RC7-Turnkey-Builder"
_REMOTE_JSON_CACHE: Dict[str, Mapping[str, Any]] = {}


class RuntimeBuildBootstrapError(RuntimeError):
    pass


def _github_authorization() -> Optional[str]:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = str(os.environ.get(key) or "").strip()
        if token:
            return "Bearer %s" % token
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "http.https://github.com/.extraheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if line.lower().startswith("authorization:"):
            value = line.split(":", 1)[1].strip()
            if value:
                return value
    return None


def _request_json(url: str) -> Mapping[str, Any]:
    cached = _REMOTE_JSON_CACHE.get(url)
    if cached is not None:
        return cached
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    authorization = _github_authorization()
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeBuildBootstrapError("REMOTE_JSON_INVALID:%s" % url)
    _REMOTE_JSON_CACHE[url] = payload
    return payload


def _download(url: str, destination: Path, expected_digest: str) -> str:
    expected = str(expected_digest or "").lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeBuildBootstrapError("UPSTREAM_SHA256_REQUIRED:%s" % url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeBuildBootstrapError(
            "UPSTREAM_SHA256_MISMATCH:%s:%s:%s" % (url, expected, actual)
        )
    return actual


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(str(archive), "r") as source:
        for info in source.infolist():
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeBuildBootstrapError(
                    "UNSAFE_BOOTSTRAP_ARCHIVE_PATH:%s" % info.filename
                ) from exc
        source.extractall(str(destination))


def acquire_ripgrep(output: Path | str, github_path: Optional[Path | str] = None) -> dict[str, Any]:
    root = Path(output).expanduser().resolve()
    release = _request_json("https://api.github.com/repos/BurntSushi/ripgrep/releases/latest")
    tag = str(release.get("tag_name") or "").strip()
    assets = release.get("assets")
    if not tag or not isinstance(assets, list):
        raise RuntimeBuildBootstrapError("RIPGREP_RELEASE_INVALID")

    expected_name = "ripgrep-%s-x86_64-pc-windows-msvc.zip" % tag
    matches = [
        row
        for row in assets
        if isinstance(row, Mapping) and str(row.get("name") or "") == expected_name
    ]
    if len(matches) != 1:
        raise RuntimeBuildBootstrapError(
            "RIPGREP_WINDOWS_X64_ASSET_NOT_UNIQUE:%s:matches=%s"
            % (expected_name, len(matches))
        )
    asset = matches[0]
    digest = str(asset.get("digest") or "")
    url = str(asset.get("browser_download_url") or "")
    if not url or not digest.startswith("sha256:"):
        raise RuntimeBuildBootstrapError("RIPGREP_RELEASE_DIGEST_REQUIRED")

    if root.exists():
        import shutil

        shutil.rmtree(str(root))
    root.mkdir(parents=True, exist_ok=True)
    archive = root / expected_name
    sha256 = _download(url, archive, digest)
    extract_root = root / "payload"
    _safe_extract(archive, extract_root)

    binaries = list(extract_root.rglob("rg.exe"))
    if len(binaries) != 1:
        raise RuntimeBuildBootstrapError(
            "RIPGREP_BINARY_NOT_UNIQUE:count=%s" % len(binaries)
        )
    binary = binaries[0].resolve()
    proc = subprocess.run(
        [str(binary), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or "ripgrep" not in text.lower():
        raise RuntimeBuildBootstrapError(
            "RIPGREP_BOOTSTRAP_SMOKE_FAILED:rc=%s:%s" % (proc.returncode, text[-1000:])
        )

    if github_path is not None:
        path_file = Path(github_path).expanduser().resolve()
        path_file.parent.mkdir(parents=True, exist_ok=True)
        with path_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(str(binary.parent) + "\n")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "payload": "ripgrep",
        "resolved_version": tag,
        "asset": expected_name,
        "sha256": sha256,
        "binary": str(binary),
        "bin_dir": str(binary.parent),
        "source": url,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.runtime-build-bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)
    ripgrep = sub.add_parser("ripgrep")
    ripgrep.add_argument("--output", required=True)
    ripgrep.add_argument("--github-path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ripgrep":
            result = acquire_ripgrep(args.output, args.github_path)
        else:
            raise RuntimeBuildBootstrapError("UNKNOWN_BOOTSTRAP_COMMAND")
    except Exception as exc:
        print(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "status": "FAIL", "reason": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
