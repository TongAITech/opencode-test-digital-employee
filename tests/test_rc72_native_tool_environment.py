"""Native tool environment must bind only platform/architecture-matched payloads."""
from pathlib import Path

import pytest
from rc7_runtime.models import ContractError
from rc7_release.rc72_tool_environment import package_tool_environment


def _native_fixture(root: Path, platform_name: str, arch: str):
    root.mkdir(parents=True)
    (root / "NATIVE_FIELD_PACKAGE.json").write_text("{}")
    runtime = root / "workspace-template/runtime"
    files = [
        "python/bin/python3", "node/bin/node", "browser/browserskill/bsk",
        "ripgrep/rg", "java/bin/java", "maven/bin/mvn", "allure/bin/allure",
        "k6/k6", "zap/ZAP_2.17.0/zap.sh",
        "browser/node-execution/node_modules/playwright/package.json",
        "node-execution/node_modules/playwright/package.json",
        "browser/browserskill-extension/manifest.json",
    ]
    suffix = {
        ("linux", "x86_64"): "linux-x64",
        ("linux", "arm64"): "linux-arm64",
        ("darwin", "x86_64"): "darwin-x64",
        ("darwin", "arm64"): "darwin-arm64",
    }[(platform_name, arch)]
    files.append("code-intelligence/codegraph/codegraph-server-" + suffix)
    chromium = "browser/pw-browsers/chromium-1234/chrome" if platform_name == "linux" else "browser/pw-browsers/chromium-1234/Chromium"
    files.append(chromium)
    for rel in files:
        path = runtime / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (runtime / "maven-repository").mkdir()
    settings = root / "packaging/rc7/maven-offline-settings.xml"
    settings.parent.mkdir(parents=True)
    settings.write_text("<settings/>")
    return runtime


@pytest.mark.parametrize("platform_name,arch,codegraph", [
    ("linux", "x86_64", "codegraph-server-linux-x64"),
    ("linux", "arm64", "codegraph-server-linux-arm64"),
    ("darwin", "x86_64", "codegraph-server-darwin-x64"),
    ("darwin", "arm64", "codegraph-server-darwin-arm64"),
])
def test_native_environment_binds_matching_architecture_and_never_windows_tools(tmp_path, platform_name, arch, codegraph):
    root = tmp_path / "native-package"
    runtime = _native_fixture(root, platform_name, arch)
    environment = package_tool_environment(root, platform_name=platform_name, architecture=arch, ambient_path="host-tools")
    assert environment["PFC_CODEGRAPH_BIN"] == str((runtime / "code-intelligence/codegraph" / codegraph).resolve())
    assert environment["PFC_PYTHON"] == str((runtime / "python/bin/python3").resolve())
    assert environment["PFC_NODE_BIN"] == str((runtime / "node/bin/node").resolve())
    assert environment["PFC_BROWSERSKILL_BIN"] == str((runtime / "browser/browserskill/bsk").resolve())
    assert environment["PFC_CHROMIUM_BIN"].startswith(str(runtime / "browser/pw-browsers"))
    assert environment["PFC_ZAP_BIN"].endswith("zap.sh")
    assert environment["PFC_K6_BIN"].endswith("/k6/k6")
    assert environment["PFC_RIPGREP_BIN"].endswith("/ripgrep/rg")
    assert environment["PATH"].split(":")[-1] == "host-tools"
    assert ".exe" not in environment["PFC_PYTHON"]
    assert ".cmd" not in environment["PFC_MAVEN_BIN"]


def test_native_environment_fails_closed_when_codegraph_architecture_missing(tmp_path):
    root = tmp_path / "native-package"
    runtime = _native_fixture(root, "linux", "arm64")
    (runtime / "code-intelligence/codegraph/codegraph-server-linux-arm64").unlink()
    with pytest.raises(ContractError, match="TOOL_REQUIRED"):
        package_tool_environment(root, platform_name="linux", architecture="arm64")
