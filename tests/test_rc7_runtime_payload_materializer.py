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


def test_browser_materializer_uses_headless_execution_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program_files = tmp_path / "Program Files"
    application = program_files / "Google/Chrome/Application"
    application.mkdir(parents=True)
    (application / "chrome.exe").write_bytes(b"chrome")
    (application / "155.0.8059.40").mkdir()
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setattr(materializer.shutil, "which", lambda name: None)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return "<html><head></head><body></body></html>"

    monkeypatch.setattr(materializer, "_run", fake_run)
    row = materializer._materialize_browser(tmp_path)

    assert row["resolved_version"] == "155.0.8059.40"
    assert (tmp_path / materializer.PACKAGE_LOCAL_BROWSER).is_file()
    assert commands
    assert "--headless=new" in commands[0]
    assert "--dump-dom" in commands[0]
    assert "--version" not in commands[0]


def test_codegraph_materializer_downloads_required_onnx_companion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe_digest = "a" * 64
    dll_digest = "b" * 64

    def fake_release(repo, *, name=None, contains=(), tag=None):
        assert repo == "codegraph-ai/CodeGraph"
        if name == "codegraph-server-win32-x64.exe":
            return {"tag_name": "v0.21.0"}, {
                "name": name,
                "digest": "sha256:" + exe_digest,
                "browser_download_url": "https://example/codegraph.exe",
            }
        if name == "onnxruntime.dll":
            return {"tag_name": "v0.21.0"}, {
                "name": name,
                "digest": "sha256:" + dll_digest,
                "browser_download_url": "https://example/onnxruntime.dll",
            }
        raise AssertionError(name)

    def fake_download(url, destination, expected_sha256):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime")
        value = str(expected_sha256)
        return value[len("sha256:") :] if value.startswith("sha256:") else value

    monkeypatch.setattr(materializer, "_release_asset", fake_release)
    monkeypatch.setattr(materializer, "_download", fake_download)
    monkeypatch.setattr(materializer, "_run", lambda *args, **kwargs: "help")

    row = materializer._materialize_codegraph(tmp_path)

    assert (tmp_path / PACKAGE_LOCAL_CODEGRAPH).is_file()
    dll = tmp_path / PACKAGE_LOCAL_CODEGRAPH.parent / "onnxruntime.dll"
    assert dll.is_file()
    assert row["sha256"] == exe_digest
    assert row["companion_files"] == [
        {
            "path": dll.as_posix(),
            "source": "https://example/onnxruntime.dll",
            "sha256": dll_digest,
        }
    ]


def test_materializer_refuses_non_windows_host(tmp_path: Path) -> None:
    if materializer.os.name == "nt":
        pytest.skip("non-Windows contract")
    with pytest.raises(materializer.RuntimePayloadMaterializerError, match="WINDOWS_RUNTIME_MATERIALIZER_REQUIRES_WINDOWS"):
        materializer.materialize(tmp_path)


def _python_payload_root(tmp_path):
    python=tmp_path/materializer.PACKAGE_LOCAL_PYTHON
    python.parent.mkdir(parents=True);python.write_bytes(b'unit-test-python-placeholder')
    probe=tmp_path/'rc7_release/python_full_capability_probe.py';probe.parent.mkdir(parents=True);probe.write_text('# unit fixture')
    marker=tmp_path/materializer.OCR_CV_MARKER;marker.parent.mkdir(parents=True);marker.write_text('{"status":"PASS"}')
    return python,marker


def test_failed_full_python_install_cannot_retain_prior_pass_marker(tmp_path,monkeypatch):
    python,marker=_python_payload_root(tmp_path)
    def fail(*args,**kwargs):raise materializer.RuntimePayloadMaterializerError('injected install failure')
    monkeypatch.setattr(materializer,'_run',fail)
    with pytest.raises(materializer.RuntimePayloadMaterializerError,match='install failure'):materializer._materialize_ocr_cv(tmp_path)
    assert not marker.exists()


def test_old_cv_pillow_marker_cannot_establish_complete_document_ocr_payload(tmp_path,monkeypatch):
    python,marker=_python_payload_root(tmp_path);commands=[]
    def old_probe(command,**kwargs):
        commands.append(list(command))
        if '--runtime-root' in command:marker.write_text(json.dumps(dict(status='PASS',versions=dict(opencv='4',pillow='10'))))
        return ''
    monkeypatch.setattr(materializer,'_run',old_probe)
    with pytest.raises(materializer.RuntimePayloadMaterializerError,match='FULL_PYTHON_CAPABILITY_PROBE_NOT_ACCEPTED'):
        materializer._materialize_ocr_cv(tmp_path)
    assert all(package in commands[0] for package in ['python-docx','openpyxl','python-pptx','pypdf','rapidocr-onnxruntime'])
    assert '-I' in commands[1]


def test_full_python_probe_refuses_interpreter_outside_declared_package(tmp_path):
    import subprocess,sys
    script=Path(materializer.__file__).with_name('python_full_capability_probe.py')
    output=tmp_path/'probe-result.json'
    child=subprocess.run([sys.executable,'-I',str(script),'--runtime-root',str(tmp_path/'foreign-runtime'),'--output',str(output)],
        capture_output=True,text=True,timeout=20)
    assert child.returncode==1
    result=json.loads(output.read_text())
    assert result['status']=='FAIL' and result['error']=='FULL_PYTHON_PACKAGE_INTERPRETER_REQUIRED'


def test_repack_excludes_build_caches_and_initial_session_state_but_preserves_product_files(tmp_path):
    root=tmp_path/'package';root.mkdir()
    (root/'product.py').write_text('print("fixture")')
    (root/'__pycache__').mkdir();(root/'__pycache__/product.pyc').write_bytes(b'cache')
    (root/'state').mkdir();(root/'state/startup-proof.json').write_text('{"CI_ONLY":true}')
    (root/'runtime-state').mkdir();(root/'runtime-state/r1.jsonl').write_text('CI initial session')
    target=tmp_path/'archive.zip';materializer._repack(root,target)
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist())=={'package/product.py','package/CHECKSUMS.sha256'}
    assert (root/'runtime-state/r1.jsonl').is_file()  # Archive filtering never deletes user data.


def test_execution_materializer_cannot_accept_playwright_without_full_graph_companion(tmp_path,monkeypatch):
    monkeypatch.setattr(materializer,'_which',lambda *args:Path('npm'))
    commands=[]
    def install(command,**kwargs):
        commands.append(list(command))
        if 'install' in command:
            package=tmp_path/'workspace-template/runtime/node-execution/node_modules/playwright/package.json'
            package.parent.mkdir(parents=True);package.write_text('{"name":"playwright","version":"fixture"}')
        return ''
    monkeypatch.setattr(materializer,'_run',install)
    with pytest.raises(materializer.RuntimePayloadMaterializerError,match='GITNEXUS_TURNKEY_PAYLOAD_INCOMPLETE'):
        materializer._materialize_playwright(tmp_path)
    assert 'gitnexus@latest' in commands[0] and '--ignore-scripts' not in commands[0]
    assert '--package-lock=true' in commands[0]


def test_bsk_041_packaging_pins_cli_extension_and_dsh_exact_release(tmp_path, monkeypatch):
    assert materializer.BSK_LOCK_VERSION == "0.4.1"
    versions = []
    downloads = []

    def release(repo, *, name=None, contains=(), tag=None):
        assert repo == "Tencent/BrowserSkill"
        versions.append((name, tag))
        if tag == "cli-v0.4.1":
            return {"tag_name": tag}, {
                "name": name, "digest": "sha256:" +
                    materializer.BSK_CLI_ARCHIVE_SHA256,
                "browser_download_url": "https://example.test/bsk-cli.zip",
            }
        if tag == "ext-v0.4.1":
            return {"tag_name": tag}, {
                "name": name, "digest": "sha256:" +
                    materializer.BSK_EXTENSION_ARCHIVE_SHA256,
                "browser_download_url": "https://example.test/bsk-ext.zip",
            }
        raise AssertionError("Moving latest or wrong tag was requested")

    def download(url, destination, expected_sha256):
        downloads.append((url, expected_sha256))
        with zipfile.ZipFile(destination, "w") as archive:
            if url.endswith("bsk-cli.zip"):
                archive.writestr("bsk.exe", "fake binary; never execute")
            else:
                archive.writestr("browser-extension/manifest.json", '{"version":"0.4.1"}')
        return str(expected_sha256).replace("sha256:", "")

    monkeypatch.setattr(materializer, "_release_asset", release)
    monkeypatch.setattr(materializer, "_download", download)
    monkeypatch.setattr(materializer, "_run", lambda *a, **k: "bsk 0.4.1")

    rows = materializer._materialize_browserskill(tmp_path)
    assert versions == [
        ("bsk-v0.4.1-x86_64-pc-windows-msvc.zip", "cli-v0.4.1"),
        ("browser-skill-extension-v0.4.1-chrome.zip", "ext-v0.4.1"),
    ]
    assert len(downloads) == 2
    assert downloads[0][1] == "sha256:" + materializer.BSK_CLI_ARCHIVE_SHA256
    assert downloads[1][1] == "sha256:" + materializer.BSK_EXTENSION_ARCHIVE_SHA256
    assert [row["resolved_version"] for row in rows] == ["0.4.1", "0.4.1"]


@pytest.mark.parametrize("bad", ["cli_digest", "cli_tag", "extension_digest", "extension_tag"])
def test_bsk_041_packaging_rejects_unexpected_bytes_or_version_before_io(
        tmp_path, monkeypatch, bad):
    downloads = []

    def release(repo, *, name=None, contains=(), tag=None):
        if tag == "cli-v0.4.1":
            return {"tag_name": "cli-v0.4.0" if bad == "cli_tag" else tag}, {
                "name": name, "digest": "sha256:" +
                    ("0" * 64 if bad == "cli_digest"
                     else materializer.BSK_CLI_ARCHIVE_SHA256),
                "browser_download_url": "https://example.test/cli",
            }
        if tag == "ext-v0.4.1":
            return {"tag_name": "ext-v0.4.0" if bad == "extension_tag" else tag}, {
                "name": name, "digest": "sha256:" +
                    ("0" * 64 if bad == "extension_digest"
                     else materializer.BSK_EXTENSION_ARCHIVE_SHA256),
                "browser_download_url": "https://example.test/ext",
            }
        raise AssertionError("Unexpected latest request")

    monkeypatch.setattr(materializer, "_release_asset", release)
    monkeypatch.setattr(materializer, "_download",
                        lambda *a, **k: downloads.append(a))
    with pytest.raises(
            materializer.RuntimePayloadMaterializerError,
            match="BROWSERSKILL_(CLI|EXTENSION)_PIN_OR_DIGEST_MISMATCH"):
        materializer._materialize_browserskill(tmp_path)
    assert downloads == []


def _build_offline_dsh_plugin_archives(home: Path, *,
                                       missing_default: str | None = None,
                                       escaped_entry: bool = False) -> None:
    """Real two-archive transport layout, without network/npm stubs."""
    from rc7_release import plugin_payload, optional_plugin_payload
    import hashlib

    required = home / plugin_payload.PAYLOAD_ARCHIVE_RELATIVE
    required.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(required, "w") as target:
        for name in plugin_payload.REQUIRED_PLUGIN_NAMES:
            version = (plugin_payload.BSK_DSH_PLUGIN_VERSION
                       if name == plugin_payload.BSK_DSH_PLUGIN_NAME else "test")
            package = plugin_payload.package_path(Path(""), name).as_posix()
            target.writestr(package + "/package.json",
                            json.dumps({"name": name, "version": version}))
        target.writestr("payload-manifest.json",
                        json.dumps({"resolved_plugins": []}))

    optional = home / optional_plugin_payload.PAYLOAD_ARCHIVE_RELATIVE
    receipts, bundled = [], []
    with zipfile.ZipFile(optional, "w") as target:
        for name in ("dsh-vision-router", "dsh-memento",
                     "@perrylink/dsh-plugin-doctor"):
            if name == missing_default:
                continue
            entry = ("../foreign.js" if escaped_entry and name == "dsh-vision-router"
                     else "lib/public-entry.js" if name == "dsh-vision-router"
                     else "index.mjs" if name == "dsh-memento" else "index.js")
            package = plugin_payload.package_path(Path(""), name).as_posix()
            raw = json.dumps({"name": name, "version": "test",
                              "main": entry}).encode("utf-8")
            target.writestr(package + "/package.json", raw)
            if not entry.startswith("../"):
                target.writestr(package + "/" + entry, "export function apply() {}\n")
            bundled.append(name)
            receipts.append({"name": name, "status": "BUNDLED",
                             "package_json_sha256": hashlib.sha256(raw).hexdigest()})
        target.writestr("payload-manifest.json", json.dumps({
            "schema_version": optional_plugin_payload.PAYLOAD_SCHEMA,
            "bundled": bundled,
            "resolved_plugins": receipts,
        }))


def test_offline_dsh_materializer_merges_p1_and_preserves_p0(tmp_path: Path) -> None:
    from rc7_release import dsh, plugin_payload

    _build_offline_dsh_plugin_archives(tmp_path)
    row = materializer._materialize_dsh_plugins(tmp_path)
    vendor = tmp_path / "workspace-template/runtime/dsh-plugins"
    assert row["default_runtime_enhancements"] == ["dsh-vision-router", "dsh-memento"]
    assert set(row["optional_runtime_plugins"]) == {
        "dsh-vision-router", "dsh-memento", "@perrylink/dsh-plugin-doctor",
    }
    assert plugin_payload.inspect_vendor(vendor)["status"] == "PASS"
    assert json.loads((vendor / "payload-manifest.json").read_text()) == {
        "resolved_plugins": [],
    }
    assert json.loads((plugin_payload.package_path(
        vendor, plugin_payload.BSK_DSH_PLUGIN_NAME) / "package.json"
    ).read_text())["version"] == "0.4.1"
    patch = tmp_path / "state/rc7-dsh.patch.yml"
    dsh.write_patch(patch, tmp_path, "python.exe", require_default_enhancements=True)
    content = patch.read_text(encoding="utf-8")
    assert "localOnlyVision: true" in content
    assert "freeFallback: false" in content
    assert "Memento" not in content or "memory.db" in content


def test_offline_dsh_materializer_refuses_missing_p1_archive(tmp_path: Path) -> None:
    from rc7_release import optional_plugin_payload

    _build_offline_dsh_plugin_archives(tmp_path)
    (tmp_path / optional_plugin_payload.PAYLOAD_ARCHIVE_RELATIVE).unlink()
    with pytest.raises(materializer.RuntimePayloadMaterializerError,
                       match="DSH_DEFAULT_ENHANCEMENT_PAYLOAD_ARCHIVE_MISSING"):
        materializer._materialize_dsh_plugins(tmp_path)


def test_offline_dsh_materializer_refuses_incomplete_p1(tmp_path: Path) -> None:
    _build_offline_dsh_plugin_archives(tmp_path, missing_default="dsh-memento")
    with pytest.raises(materializer.RuntimePayloadMaterializerError,
                       match="DSH_DEFAULT_ENHANCEMENT_PAYLOAD_INCOMPLETE:dsh-memento"):
        materializer._materialize_dsh_plugins(tmp_path)


def test_offline_dsh_materializer_refuses_escape_entry(tmp_path: Path) -> None:
    _build_offline_dsh_plugin_archives(tmp_path, escaped_entry=True)
    with pytest.raises(materializer.RuntimePayloadMaterializerError,
                       match="DSH_DEFAULT_ENHANCEMENT_ENTRY_ESCAPE:dsh-vision-router"):
        materializer._materialize_dsh_plugins(tmp_path)
