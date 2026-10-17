from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .package import PACKAGE_LOCAL_BROWSER, PACKAGE_LOCAL_CODEGRAPH, PACKAGE_LOCAL_PYTHON, sha256_file, write_checksums
from .runtime_delivery_contract import OCR_CV_MARKER, verify_runtime_delivery


SCHEMA_VERSION = "pfc.aitest.rc7.runtime-payload-materializer.v1"
INVENTORY_FILE = "RUNTIME_PAYLOADS.json"
USER_AGENT = "PFC-AITest-RC7-Turnkey-Builder"


class RuntimePayloadMaterializerError(RuntimeError):
    pass


def _run(command: Sequence[str], *, cwd: Optional[Path] = None, timeout: int = 600, env: Optional[Mapping[str, str]] = None) -> str:
    proc = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    text = (proc.stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimePayloadMaterializerError(
            "COMMAND_FAILED:%s:rc=%s:%s" % (" ".join(command), proc.returncode, text[-4000:])
        )
    return text


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise RuntimePayloadMaterializerError("RUNTIME_SOURCE_DIR_MISSING:%s" % source)
    if destination.exists():
        shutil.rmtree(str(destination))
    shutil.copytree(str(source), str(destination))


def _copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimePayloadMaterializerError("RUNTIME_SOURCE_FILE_MISSING:%s" % source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(destination))


def _which(*names: str) -> Path:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    raise RuntimePayloadMaterializerError("RUNTIME_COMMAND_NOT_FOUND:%s" % ",".join(names))


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _request_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimePayloadMaterializerError("REMOTE_JSON_INVALID:%s" % url)
    return payload


def _download(url: str, destination: Path, expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimePayloadMaterializerError("UPSTREAM_SHA256_REQUIRED:%s" % url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
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
        raise RuntimePayloadMaterializerError("UPSTREAM_SHA256_MISMATCH:%s:%s:%s" % (url, expected, actual))
    return actual


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(str(archive), "r") as handle:
        for info in handle.infolist():
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimePayloadMaterializerError("UNSAFE_RUNTIME_ARCHIVE_PATH:%s" % info.filename) from exc
        handle.extractall(str(destination))


def _release_asset(repo: str, *, name: Optional[str] = None, contains: Sequence[str] = (), tag: Optional[str] = None) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    if tag:
        release_url = "https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag)
    else:
        release_url = "https://api.github.com/repos/%s/releases/latest" % repo
    release = _request_json(release_url)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimePayloadMaterializerError("RELEASE_ASSETS_INVALID:%s" % repo)
    matches = []
    for row in assets:
        if not isinstance(row, Mapping):
            continue
        asset_name = str(row.get("name") or "")
        if name and asset_name != name:
            continue
        if contains and not all(token.lower() in asset_name.lower() for token in contains):
            continue
        matches.append(row)
    if len(matches) != 1:
        raise RuntimePayloadMaterializerError(
            "RELEASE_ASSET_NOT_UNIQUE:%s:name=%s:contains=%s:matches=%s"
            % (repo, name or "", ",".join(contains), ",".join(str(row.get("name")) for row in matches))
        )
    asset = matches[0]
    if not str(asset.get("digest") or "").startswith("sha256:"):
        raise RuntimePayloadMaterializerError("RELEASE_ASSET_DIGEST_REQUIRED:%s:%s" % (repo, asset.get("name")))
    return release, asset


def _record(name: str, target: Path, *, version: Optional[str], source: str, sha256: Optional[str] = None) -> Dict[str, Any]:
    return {
        "payload": name,
        "target": target.as_posix(),
        "resolved_version": version,
        "source": source,
        "sha256": sha256,
    }


def _materialize_node(root: Path) -> Dict[str, Any]:
    source = _which("node.exe", "node")
    target_dir = root / "workspace-template/runtime/node"
    _copy_tree(source.parent, target_dir)
    target = target_dir / "node.exe"
    version = _run([str(target), "--version"], cwd=root, timeout=30).strip()
    return _record("node", target, version=version, source="RUNNER_DISCOVERY", sha256=_sha256(target))


def _chrome_version_from_layout(application_dir: Path) -> Optional[str]:
    versions = []
    for child in application_dir.iterdir():
        if not child.is_dir() or not re.fullmatch(r"\d+(?:\.\d+){3}", child.name):
            continue
        versions.append((tuple(int(part) for part in child.name.split(".")), child.name))
    if not versions:
        return None
    return max(versions)[1]


def _materialize_browser(root: Path) -> Dict[str, Any]:
    candidates = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    which = shutil.which("chrome.exe") or shutil.which("chrome")
    if which:
        candidates.insert(0, Path(which))
    source = next((path.resolve() for path in candidates if path.is_file()), None)
    if source is None:
        raise RuntimePayloadMaterializerError("RUNNER_CHROME_NOT_FOUND")
    version = _chrome_version_from_layout(source.parent)
    target_dir = root / PACKAGE_LOCAL_BROWSER.parent
    _copy_tree(source.parent, target_dir)
    target = root / PACKAGE_LOCAL_BROWSER
    with tempfile.TemporaryDirectory(prefix="rc7-chrome-profile-") as profile:
        output = _run(
            [
                str(target),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                "--no-first-run",
                "--no-default-browser-check",
                "--user-data-dir=%s" % profile,
                "--dump-dom",
                "about:blank",
            ],
            cwd=root,
            timeout=60,
        )
    if "<html" not in output.lower():
        raise RuntimePayloadMaterializerError("PACKAGE_BROWSER_HEADLESS_SMOKE_FAILED")
    return _record("controlled_browser", target, version=version, source="RUNNER_IMAGE_GOOGLE_CHROME", sha256=_sha256(target))


def _materialize_java(root: Path) -> Dict[str, Any]:
    source_home = None
    for key in ("JAVA_HOME_17_X64", "JAVA_HOME"):
        value = os.environ.get(key)
        if value and (Path(value) / "bin/java.exe").is_file():
            source_home = Path(value).resolve()
            break
    if source_home is None:
        java = _which("java.exe", "java")
        source_home = java.parent.parent
    target_dir = root / "workspace-template/runtime/java"
    _copy_tree(source_home, target_dir)
    java = target_dir / "bin/java.exe"
    version = _run([str(java), "-version"], cwd=root, timeout=30).splitlines()[0].strip()
    return _record("jdk", target_dir, version=version, source="RUNNER_DISCOVERY", sha256=_sha256(java))


def _materialize_maven(root: Path) -> Dict[str, Any]:
    mvn = _which("mvn.cmd", "mvn")
    source_home = mvn.parent.parent
    target_dir = root / "workspace-template/runtime/maven"
    _copy_tree(source_home, target_dir)
    target = target_dir / "bin/mvn.cmd"
    java_home = root / "workspace-template/runtime/java"
    env = dict(os.environ)
    env["JAVA_HOME"] = str(java_home)
    version = _run([str(target), "-version"], cwd=root, timeout=60, env=env).splitlines()[0].strip()
    return _record("maven", target_dir, version=version, source="RUNNER_DISCOVERY", sha256=_sha256(target))


def _materialize_ripgrep(root: Path) -> Dict[str, Any]:
    source = _which("rg.exe", "rg")
    target = root / "workspace-template/runtime/ripgrep/rg.exe"
    _copy_file(source, target)
    version = _run([str(target), "--version"], cwd=root, timeout=30).splitlines()[0].strip()
    return _record("ripgrep", target.parent, version=version, source="RUNNER_DISCOVERY", sha256=_sha256(target))


def _materialize_dsh_plugins(root: Path) -> Dict[str, Any]:
    archive = root / "rc7_release/vendor/dsh-plugins-payload.zip"
    if not archive.is_file():
        raise RuntimePayloadMaterializerError("DSH_PLUGIN_PAYLOAD_ARCHIVE_MISSING")
    target = root / "workspace-template/runtime/dsh-plugins"
    if target.exists():
        shutil.rmtree(str(target))
    _safe_extract(archive, target)
    manifest = target / "payload-manifest.json"
    if not manifest.is_file():
        raise RuntimePayloadMaterializerError("DSH_PLUGIN_RUNTIME_MANIFEST_MISSING")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    versions = [str(row.get("name")) + "@" + str(row.get("resolved_version")) for row in payload.get("resolved_plugins", [])]
    return _record("dsh_plugins", target, version=",".join(versions), source="PACKAGE_VENDOR_ARCHIVE", sha256=_sha256(archive))


def _materialize_browserskill(root: Path) -> List[Dict[str, Any]]:
    cli_release, cli_asset = _release_asset("Tencent/BrowserSkill", contains=("x86_64-pc-windows-msvc", ".zip"))
    tag = str(cli_release.get("tag_name") or "")
    version = tag.removeprefix("cli-v")
    if not version:
        raise RuntimePayloadMaterializerError("BROWSERSKILL_RELEASE_VERSION_INVALID")
    with tempfile.TemporaryDirectory(prefix="rc7-bsk-") as temp:
        archive = Path(temp) / str(cli_asset["name"])
        _download(str(cli_asset["browser_download_url"]), archive, str(cli_asset["digest"]))
        target = root / "workspace-template/runtime/browser/browserskill"
        if target.exists():
            shutil.rmtree(str(target))
        _safe_extract(archive, target)
    bsk = next(iter(target.rglob("bsk.exe")), None)
    if bsk is None:
        raise RuntimePayloadMaterializerError("BROWSERSKILL_BSK_EXE_MISSING")
    _run([str(bsk), "--version"], cwd=root, timeout=30)

    ext_release, ext_asset = _release_asset("Tencent/BrowserSkill", contains=("chrome.zip",), tag="ext-v%s" % version)
    ext_target = root / "workspace-template/runtime/browser/browserskill-extension"
    with tempfile.TemporaryDirectory(prefix="rc7-bsk-ext-") as temp:
        archive = Path(temp) / str(ext_asset["name"])
        _download(str(ext_asset["browser_download_url"]), archive, str(ext_asset["digest"]))
        if ext_target.exists():
            shutil.rmtree(str(ext_target))
        _safe_extract(archive, ext_target)
    manifests = list(ext_target.rglob("manifest.json"))
    if not manifests:
        raise RuntimePayloadMaterializerError("BROWSERSKILL_EXTENSION_MANIFEST_MISSING")
    return [
        _record("browserskill", target, version=version, source=str(cli_asset["browser_download_url"]), sha256=str(cli_asset["digest"]).removeprefix("sha256:")),
        _record("browserskill_extension", ext_target, version=str(ext_release.get("tag_name") or "").removeprefix("ext-v"), source=str(ext_asset["browser_download_url"]), sha256=str(ext_asset["digest"]).removeprefix("sha256:")),
    ]


def _materialize_codegraph(root: Path) -> Dict[str, Any]:
    release, asset = _release_asset("codegraph-ai/CodeGraph", name="codegraph-server-win32-x64.exe")
    dll_release, dll_asset = _release_asset("codegraph-ai/CodeGraph", name="onnxruntime.dll")
    release_tag = str(release.get("tag_name") or release.get("name") or "")
    dll_tag = str(dll_release.get("tag_name") or dll_release.get("name") or "")
    if release_tag != dll_tag:
        raise RuntimePayloadMaterializerError("CODEGRAPH_COMPANION_RELEASE_MISMATCH:%s:%s" % (release_tag, dll_tag))
    target = root / PACKAGE_LOCAL_CODEGRAPH
    dll_target = target.parent / "onnxruntime.dll"
    digest = _download(str(asset["browser_download_url"]), target, str(asset["digest"]))
    dll_digest = _download(str(dll_asset["browser_download_url"]), dll_target, str(dll_asset["digest"]))
    _run([str(target), "--help"], cwd=root, timeout=60)
    row = _record("codegraph", target, version=release_tag, source=str(asset["browser_download_url"]), sha256=digest)
    row["companion_files"] = [
        {
            "path": dll_target.as_posix(),
            "source": str(dll_asset["browser_download_url"]),
            "sha256": dll_digest,
        }
    ]
    return row


def _materialize_playwright(root: Path) -> Dict[str, Any]:
    npm = _which("npm.cmd", "npm")
    target = root / "workspace-template/runtime/node-execution"
    target.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
    _run(
        [str(npm), "install", "--prefix", str(target), "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=false", "playwright@latest"],
        cwd=root,
        timeout=600,
        env=env,
    )
    package_json = target / "node_modules/playwright/package.json"
    if not package_json.is_file():
        raise RuntimePayloadMaterializerError("PLAYWRIGHT_PACKAGE_MISSING")
    manifest = json.loads(package_json.read_text(encoding="utf-8"))
    node = root / "workspace-template/runtime/node/node.exe"
    _run([str(node), "-e", "require('playwright'); console.log('playwright-ok')"], cwd=target, timeout=60)
    return _record("playwright", target / "node_modules/playwright", version=str(manifest.get("version") or ""), source="NPM_LATEST_AT_BUILD", sha256=_sha256(package_json))


def _materialize_ocr_cv(root: Path) -> Dict[str, Any]:
    python = root / PACKAGE_LOCAL_PYTHON
    if not python.is_file():
        raise RuntimePayloadMaterializerError("PACKAGE_LOCAL_PYTHON_REQUIRED_FOR_OCR_CV")
    _run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "pillow", "opencv-python-headless"],
        cwd=root,
        timeout=900,
    )
    output = _run(
        [str(python), "-c", "import cv2, PIL, json; print(json.dumps({'opencv':cv2.__version__,'pillow':PIL.__version__}))"],
        cwd=root,
        timeout=60,
    ).strip().splitlines()[-1]
    versions = json.loads(output)
    marker = root / OCR_CV_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"status": "PASS", "versions": versions}, sort_keys=True) + "\n", encoding="utf-8")
    return _record("local_ocr_cv", marker.parent.parent, version="opencv=%s,pillow=%s" % (versions["opencv"], versions["pillow"]), source="PYPI_BUILD_TIME_RESOLUTION", sha256=_sha256(marker))


def _seed_maven_repository(root: Path) -> Dict[str, Any]:
    repo = root / "workspace-template/runtime/maven-repository"
    repo.mkdir(parents=True, exist_ok=True)
    mvn = root / "workspace-template/runtime/maven/bin/mvn.cmd"
    java_home = root / "workspace-template/runtime/java"
    env = dict(os.environ)
    env["JAVA_HOME"] = str(java_home)
    coordinates = (
        "org.junit.jupiter:junit-jupiter:LATEST",
        "org.apache.maven.plugins:maven-surefire-plugin:LATEST",
        "org.apache.maven.plugins:maven-failsafe-plugin:LATEST",
        "org.jacoco:jacoco-maven-plugin:LATEST",
    )
    for artifact in coordinates:
        _run(
            [str(mvn), "-B", "-q", "org.apache.maven.plugins:maven-dependency-plugin:LATEST:get", "-Dmaven.repo.local=%s" % repo, "-Dartifact=%s" % artifact, "-Dtransitive=true"],
            cwd=root,
            timeout=900,
            env=env,
        )
    if not list(repo.rglob("*.pom")):
        raise RuntimePayloadMaterializerError("MAVEN_BOOTSTRAP_REPOSITORY_EMPTY")
    return _record("maven_bootstrap_repository", repo, version="JUNIT_SUREFIRE_FAILSAFE_JACOCO_RESOLVED_AT_BUILD", source="MAVEN_CENTRAL_BUILD_TIME", sha256=None)


def _materialize_release_zip(root: Path, payload: str, repo: str, contains: Sequence[str], relative_target: str) -> Dict[str, Any]:
    release, asset = _release_asset(repo, contains=contains)
    target = root / relative_target
    with tempfile.TemporaryDirectory(prefix="rc7-%s-" % payload) as temp:
        archive = Path(temp) / str(asset["name"])
        digest = _download(str(asset["browser_download_url"]), archive, str(asset["digest"]))
        if target.exists():
            shutil.rmtree(str(target))
        _safe_extract(archive, target)
    return _record(payload, target, version=str(release.get("tag_name") or release.get("name") or ""), source=str(asset["browser_download_url"]), sha256=digest)


def _materialize_allure(root: Path) -> Dict[str, Any]:
    return _materialize_release_zip(root, "allure", "allure-framework/allure2", ("allure-", ".zip"), "workspace-template/runtime/allure")


def _materialize_k6(root: Path) -> Dict[str, Any]:
    return _materialize_release_zip(root, "k6", "grafana/k6", ("windows-amd64.zip",), "workspace-template/runtime/k6")


def _materialize_zap(root: Path) -> Dict[str, Any]:
    return _materialize_release_zip(root, "zap", "zaproxy/zaproxy", ("Crossplatform.zip",), "workspace-template/runtime/zap")


def _update_manifest(root: Path, inventory: Sequence[Mapping[str, Any]]) -> None:
    path = root / "PACKAGE_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    by_name = {str(row["payload"]): dict(row) for row in inventory}
    for name, field, target in (
        ("codegraph", "package_local_codegraph", PACKAGE_LOCAL_CODEGRAPH),
        ("controlled_browser", "package_local_browser", PACKAGE_LOCAL_BROWSER),
    ):
        row = by_name[name]
        manifest[field] = {
            "path": target.as_posix(),
            "bundled": True,
            "resolved_version": row.get("resolved_version"),
            "sha256": row.get("sha256"),
        }
    manifest["runtime_payload_inventory"] = INVENTORY_FILE
    manifest["delivery_runtime_complete"] = False
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_inventory(root: Path, inventory: Sequence[Mapping[str, Any]]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "payloads": list(inventory),
    }
    (root / INVENTORY_FILE).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _repack(root: Path, zip_path: Path) -> str:
    write_checksums(root)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                arc = Path(root.name) / path.relative_to(root)
                archive.write(str(path), arc.as_posix())
    digest = _sha256(zip_path)
    Path(str(zip_path) + ".sha256").write_text("%s  %s\n" % (digest, zip_path.name), encoding="utf-8")
    return digest


def materialize(package_root: Path | str, zip_path: Optional[Path | str] = None) -> Dict[str, Any]:
    if os.name != "nt":
        raise RuntimePayloadMaterializerError("WINDOWS_RUNTIME_MATERIALIZER_REQUIRES_WINDOWS")
    root = Path(package_root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimePayloadMaterializerError("PACKAGE_ROOT_NOT_FOUND:%s" % root)

    inventory: List[Dict[str, Any]] = []
    inventory.append(_materialize_node(root))
    inventory.append(_materialize_browser(root))
    inventory.append(_materialize_java(root))
    inventory.append(_materialize_maven(root))
    inventory.append(_materialize_ripgrep(root))
    inventory.append(_materialize_dsh_plugins(root))
    inventory.extend(_materialize_browserskill(root))
    inventory.append(_materialize_codegraph(root))
    inventory.append(_materialize_playwright(root))
    inventory.append(_materialize_ocr_cv(root))
    inventory.append(_seed_maven_repository(root))
    inventory.append(_materialize_allure(root))
    inventory.append(_materialize_k6(root))
    inventory.append(_materialize_zap(root))

    _write_inventory(root, inventory)
    _update_manifest(root, inventory)
    write_checksums(root)
    contract = verify_runtime_delivery(root)
    manifest_path = root / "PACKAGE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["delivery_runtime_complete"] = True
    manifest["delivery_runtime_contract"] = contract["schema_version"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_checksums(root)

    zip_digest = None
    if zip_path is not None:
        zip_digest = _repack(root, Path(zip_path).expanduser().resolve())

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "delivery_runtime_complete": True,
        "package_root": str(root),
        "payload_count": len(inventory),
        "payloads": inventory,
        "zip_sha256": zip_digest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.runtime_payload_materializer")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--zip")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = materialize(args.package_root, args.zip)
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())