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
