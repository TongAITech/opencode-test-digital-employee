from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_release.runtime_clean_smoke import RuntimeCleanSmokeError, qualify_runtime_clean_smoke


REQUIRED = {
    "python": "workspace-template/runtime/python/python.exe",
    "node": "workspace-template/runtime/node/node.exe",
    "controlled_browser": "workspace-template/runtime/browser/chrome-win64/chrome.exe",
    "browserskill": "workspace-template/runtime/browser/browserskill",
    "browserskill_extension": "workspace-template/runtime/browser/browserskill-extension",
    "playwright": "workspace-template/runtime/node-execution/node_modules/playwright",
    "codegraph": "workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe",
    "ripgrep": "workspace-template/runtime/ripgrep",
    "jdk": "workspace-template/runtime/java",
    "maven": "workspace-template/runtime/maven",
    "maven_bootstrap_repository": "workspace-template/runtime/maven-repository",
    "allure": "workspace-template/runtime/allure",
    "k6": "workspace-template/runtime/k6",
    "zap": "workspace-template/runtime/zap",
    "local_ocr_cv": "workspace-template/runtime/python",
    "dsh_plugins": "workspace-template/runtime/dsh-plugins",
}


def _file(root: Path, relative: str, content: str = "x") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _layout(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    root.mkdir()
    lock = {"payloads": {name: {"required_for_delivery": True, "relative_target": target} for name, target in REQUIRED.items()}}
    _file(root, "runtime-lock.json", json.dumps(lock))
    _file(
        root,
        "PACKAGE_MANIFEST.json",
        json.dumps(
            {
                "package_local_browser": {"bundled": True},
                "package_local_codegraph": {"bundled": True},
            }
        ),
    )

    for relative in (
        "workspace-template/runtime/python/python.exe",
        "workspace-template/runtime/node/node.exe",
        "workspace-template/runtime/browser/chrome-win64/chrome.exe",
        "workspace-template/runtime/browser/browserskill/bin/bsk.exe",
        "workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe",
        "workspace-template/runtime/code-intelligence/codegraph/onnxruntime.dll",
        "workspace-template/runtime/ripgrep/bin/rg.exe",
        "workspace-template/runtime/java/bin/java.exe",
        "workspace-template/runtime/maven/bin/mvn.cmd",
        "workspace-template/runtime/allure/allure-x/bin/allure.bat",
        "workspace-template/runtime/k6/k6-x/k6.exe",
        "workspace-template/runtime/zap/ZAP_x/zap-2.17.0.jar",
        "workspace-template/runtime/dsh-plugins/node_modules/dsh-routing-suite/package.json",
        "workspace-template/runtime/node-execution/node_modules/playwright/package.json",
        "workspace-template/runtime/python/.rc7-capabilities/local_ocr_cv.json",
    ):
        _file(root, relative)

    _file(
        root,
        "workspace-template/runtime/browser/browserskill-extension/manifest.json",
        json.dumps({"name": "BrowserSkill", "version": "0.3.3"}),
    )
    for relative in (
        "workspace-template/runtime/maven-repository/org/junit/jupiter/junit-jupiter/1/a.pom",
        "workspace-template/runtime/maven-repository/org/apache/maven/plugins/maven-surefire-plugin/1/a.pom",
        "workspace-template/runtime/maven-repository/org/apache/maven/plugins/maven-failsafe-plugin/1/a.pom",
        "workspace-template/runtime/maven-repository/org/jacoco/jacoco-maven-plugin/1/a.pom",
    ):
        _file(root, relative, "<project/>")
    return root


class FakeRunner:
    def __init__(self, browser_ok: bool = True) -> None:
        self.calls = []
        self.browser_ok = browser_ok

    def __call__(self, command, *, cwd, env, label, timeout=60):
        self.calls.append({"command": list(command), "cwd": Path(cwd), "env": dict(env), "label": label, "timeout": timeout})
        if label == "controlled_browser":
            return "<html>RC7_RUNTIME_CLEAN_BROWSER_SMOKE_OK</html>" if self.browser_ok else "<html>wrong</html>"
        if label == "dsh_plugins":
            return json.dumps({"status": "PASS"})
        return "%s-ok" % label


def test_clean_runtime_smoke_uses_package_local_product_tools(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    runner = FakeRunner()

    result = qualify_runtime_clean_smoke(root, runner=runner, require_windows=False)

    assert result["status"] == "PASS"
    assert result["delivery_runtime_complete"] is True
    assert result["required_payload_count"] == 16
    assert result["smoke_count"] >= 15

    product_labels = {
        "python",
        "node",
        "controlled_browser",
        "browserskill",
        "codegraph",
        "ripgrep",
        "jdk",
        "playwright",
        "local_ocr_cv",
        "k6",
        "zap",
        "dsh_plugins",
    }
    for call in runner.calls:
        command = call["command"]
        if call["label"] in product_labels:
            resolved_command = Path(command[0]).resolve()
            resolved_root = root.resolve()
            assert resolved_command == resolved_root or resolved_root in resolved_command.parents
        if call["label"] in {"maven", "allure"}:
            # cmd.exe is an OS script host; the actual launcher embedded in the
            # command line must be package-local.
            assert Path(command[0]).name.lower() == "cmd.exe"
            assert str(root.resolve()) in command[-1]
        if call["label"] in {"maven", "allure", "zap", "jdk"}:
            assert call["env"]["JAVA_HOME"] == str((root / "workspace-template/runtime/java").resolve())


def test_missing_required_runtime_fails_closed(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    (root / "workspace-template/runtime/node/node.exe").unlink()
    with pytest.raises(Exception, match="REQUIRED_PAYLOAD_MISSING:node"):
        qualify_runtime_clean_smoke(root, runner=FakeRunner(), require_windows=False)


def test_browser_smoke_requires_expected_dom_marker(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    with pytest.raises(RuntimeCleanSmokeError, match="CONTROLLED_BROWSER_MARKER_MISSING"):
        qualify_runtime_clean_smoke(root, runner=FakeRunner(browser_ok=False), require_windows=False)


def test_browser_smoke_restores_setup_metrics_package_state(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    original = _file(
        root,
        "workspace-template/runtime/browser/chrome-win64/SetupMetrics/original.pma",
        "transport-state",
    )
    created = root / "workspace-template/runtime/browser/chrome-win64/SetupMetrics/runtime-created.pma"

    class MutatingBrowserRunner(FakeRunner):
        def __call__(self, command, *, cwd, env, label, timeout=60):
            if label == "controlled_browser":
                original.write_text("mutated-by-chrome", encoding="utf-8")
                created.write_text("runtime-telemetry", encoding="utf-8")
            return super().__call__(command, cwd=cwd, env=env, label=label, timeout=timeout)

    result = qualify_runtime_clean_smoke(root, runner=MutatingBrowserRunner(), require_windows=False)

    assert result["status"] == "PASS"
    assert original.read_text(encoding="utf-8") == "transport-state"
    assert not created.exists()


def test_ambiguous_runtime_binary_fails_closed(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    _file(root, "workspace-template/runtime/ripgrep/other/rg.exe")
    with pytest.raises(RuntimeCleanSmokeError, match="RIPGREP_EXPECTED_ONE"):
        qualify_runtime_clean_smoke(root, runner=FakeRunner(), require_windows=False)


def test_extension_requires_identity(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    _file(root, "workspace-template/runtime/browser/browserskill-extension/manifest.json", json.dumps({"name": "", "version": ""}))
    with pytest.raises(RuntimeCleanSmokeError, match="BROWSERSKILL_EXTENSION_IDENTITY_MISSING"):
        qualify_runtime_clean_smoke(root, runner=FakeRunner(), require_windows=False)
