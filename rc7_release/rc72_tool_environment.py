"""Bind platform-native carried tools without host PATH fallback."""
import os
from pathlib import Path

from rc7_runtime.models import ContractError

FIXED_FILES = {
    "PFC_PYTHON": "python/python.exe",
    "PFC_NODE_BIN": "node/node.exe",
    "PFC_CODEGRAPH_BIN": "code-intelligence/codegraph/codegraph-server-win32-x64.exe",
    "PFC_BROWSERSKILL_BIN": "browser/browserskill/bsk.exe",
    "PFC_RIPGREP_BIN": "ripgrep/rg.exe",
    "PFC_JAVA_BIN": "java/bin/java.exe",
    "PFC_MAVEN_BIN": "maven/bin/mvn.cmd",
}
WINDOWS_DISCOVERED_FILES = {
    "PFC_ALLURE_BIN": ("allure", "allure.bat"),
    "PFC_K6_BIN": ("k6", "k6.exe"),
    "PFC_ZAP_BIN": ("zap", "zap.bat"),
}
NATIVE_FILES = {
    "PFC_PYTHON": "python/bin/python3",
    "PFC_NODE_BIN": "node/bin/node",
    "PFC_BROWSERSKILL_BIN": "browser/browserskill/bsk",
    "PFC_RIPGREP_BIN": "ripgrep/rg",
    "PFC_JAVA_BIN": "java/bin/java",
    "PFC_MAVEN_BIN": "maven/bin/mvn",
    "PFC_ALLURE_BIN": "allure/bin/allure",
    "PFC_K6_BIN": "k6/k6",
}
OWNED_NAMES = frozenset(FIXED_FILES) | frozenset(WINDOWS_DISCOVERED_FILES) | {
    "PFC_ALLURE_BIN", "PFC_K6_BIN", "PFC_ZAP_BIN", "PFC_CHROMIUM_BIN",
    "PFC_CODEGRAPH_BIN", "PATH", "JAVA_HOME", "MAVEN_HOME",
    "PFC_MAVEN_REPO", "PFC_MAVEN_SETTINGS", "MAVEN_ARGS",
}


def _native_codegraph_name(platform_name, architecture):
    if platform_name == "linux":
        suffix = "linux-x64" if architecture in ("x86_64", "amd64") else "linux-arm64"
    elif platform_name == "darwin":
        suffix = "darwin-x64" if architecture in ("x86_64", "amd64") else "darwin-arm64"
    else:
        raise ContractError("MISSION_PACKAGE_PLATFORM_UNSUPPORTED")
    return "codegraph-server-" + suffix


def _contained_file(path, runtime, name):
    if not path.is_file():
        raise ContractError("MISSION_PACKAGE_TOOL_REQUIRED:" + name)
    try:
        path.resolve().relative_to(runtime.resolve())
    except ValueError:
        raise ContractError("MISSION_PACKAGE_TOOL_OUTSIDE_RUNTIME:" + name) from None
    if path.is_symlink():
        raise ContractError("MISSION_PACKAGE_TOOL_SYMLINK_FORBIDDEN:" + name)
    return path.resolve()


def package_tool_environment(package_root, *, ambient_path=None, platform_name=None, architecture=None):
    root = Path(package_root).resolve()
    if not (root / "NATIVE_FIELD_PACKAGE.json").is_file() and not (root / "PACKAGE_MANIFEST.json").is_file():
        return {}
    runtime = root / "workspace-template/runtime"
    if platform_name is None:
        if (root / "NATIVE_FIELD_PACKAGE.json").is_file():
            platform_name = "darwin" if __import__("sys").platform == "darwin" else "linux"
        elif (root / "PACKAGE_MANIFEST.json").is_file():
            platform_name = "windows"
        else:
            platform_name = "windows" if os.name == "nt" else ("darwin" if __import__("sys").platform == "darwin" else "linux")
    if architecture is None:
        architecture = __import__("platform").machine().lower()

    if platform_name == "windows":
        fixed = dict(FIXED_FILES)
        discovered = dict(WINDOWS_DISCOVERED_FILES)
        codegraph = None
    elif platform_name in ("linux", "darwin"):
        fixed = dict(NATIVE_FILES)
        discovered = {
            "PFC_ZAP_BIN": ("zap", "zap.sh"),
        }
        codegraph = "code-intelligence/codegraph/" + _native_codegraph_name(platform_name, architecture)
        fixed["PFC_CODEGRAPH_BIN"] = codegraph
    else:
        raise ContractError("MISSION_PACKAGE_PLATFORM_UNSUPPORTED")

    def contained(relative, name):
        return _contained_file(runtime / relative, runtime, name)

    result = {name: str(contained(relative, name)) for name, relative in fixed.items()}
    for name, (directory, filename) in discovered.items():
        matches = [path for path in (runtime / directory).rglob(filename) if path.is_file()]
        if len(matches) != 1:
            raise ContractError("MISSION_PACKAGE_TOOL_NOT_UNIQUE:" + name)
        result[name] = str(contained(matches[0].relative_to(runtime), name))

    if platform_name != "windows":
        if platform_name == "linux":
            chromium_candidates = list((runtime / "browser/pw-browsers").rglob("chrome"))
        else:
            chromium_candidates = list((runtime / "browser/pw-browsers").rglob("Chromium"))
        chromium_candidates = [p for p in chromium_candidates if p.is_file()]
        if len(chromium_candidates) != 1:
            raise ContractError("MISSION_PACKAGE_TOOL_NOT_UNIQUE:PFC_CHROMIUM_BIN")
        result["PFC_CHROMIUM_BIN"] = str(_contained_file(chromium_candidates[0], runtime, "PFC_CHROMIUM_BIN"))

    repository = runtime / "maven-repository"
    settings = root / "packaging/rc7/maven-offline-settings.xml"
    if not repository.is_dir() or not settings.is_file():
        raise ContractError("MISSION_PACKAGE_OFFLINE_MAVEN_REQUIRED")
    try:
        repository.resolve().relative_to(runtime.resolve())
        settings.resolve().relative_to(root)
    except ValueError:
        raise ContractError("MISSION_PACKAGE_OFFLINE_MAVEN_OUTSIDE_ROOT") from None
    result.update(
        JAVA_HOME=str(runtime / "java"),
        MAVEN_HOME=str(runtime / "maven"),
        PFC_MAVEN_REPO=str(repository),
        PFC_MAVEN_SETTINGS=str(settings),
        MAVEN_ARGS='-o -s "' + str(settings) + '" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local="' + str(repository) + '"',
    )
    directories = []
    for name in (
        "PFC_NODE_BIN", "PFC_BROWSERSKILL_BIN", "PFC_RIPGREP_BIN",
        "PFC_MAVEN_BIN", "PFC_JAVA_BIN", "PFC_ALLURE_BIN",
        "PFC_K6_BIN", "PFC_ZAP_BIN", "PFC_CODEGRAPH_BIN",
    ):
        value = str(Path(result[name]).parent)
        if value not in directories:
            directories.append(value)
    tail = os.environ.get("PATH", "") if ambient_path is None else ambient_path
    result["PATH"] = os.pathsep.join(directories + ([tail] if tail else []))
    return result
