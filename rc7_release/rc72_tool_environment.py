"""Bind carried tool paths for native Mission processes, without host fallback.

This selects paths, not capability/Field acceptance. The package verifier and
native execution gates remain responsible for integrity and actual effects.
"""
import os
from pathlib import Path

from rc7_runtime.models import ContractError


FIXED_FILES = {
    'PFC_PYTHON': 'python/python.exe',
    'PFC_NODE_BIN': 'node/node.exe',
    'PFC_CODEGRAPH_BIN': 'code-intelligence/codegraph/codegraph-server-win32-x64.exe',
    'PFC_CHROMIUM_BIN': 'browser/chrome-win64/chrome.exe',
    'PFC_BROWSERSKILL_BIN': 'browser/browserskill/bsk.exe',
    'PFC_RIPGREP_BIN': 'ripgrep/rg.exe',
    'PFC_JAVA_BIN': 'java/bin/java.exe',
    'PFC_MAVEN_BIN': 'maven/bin/mvn.cmd',
}
DISCOVERED_FILES = {'PFC_K6_BIN': ('k6', 'k6.exe'), 'PFC_ALLURE_BIN': ('allure', 'allure.bat'), 'PFC_ZAP_BIN': ('zap', 'zap.bat')}
OWNED_NAMES = frozenset(FIXED_FILES) | frozenset(DISCOVERED_FILES) | {
    'PATH', 'JAVA_HOME', 'MAVEN_HOME', 'PFC_MAVEN_REPO', 'PFC_MAVEN_SETTINGS', 'MAVEN_ARGS'}


def package_tool_environment(package_root, *, ambient_path=None):
    root = Path(package_root).resolve()
    # Component engineering fixtures do not assert a full carried runtime.
    if not (root/'PACKAGE_MANIFEST.json').is_file():
        return {}
    runtime = root/'workspace-template/runtime'

    def contained_file(path, name):
        if path.is_symlink() or not path.is_file():
            raise ContractError('MISSION_PACKAGE_TOOL_REQUIRED:'+name)
        try:
            path.resolve().relative_to(runtime)
        except ValueError:
            raise ContractError('MISSION_PACKAGE_TOOL_OUTSIDE_RUNTIME:'+name) from None
        return path.resolve()

    result = {name: str(contained_file(runtime/relative, name)) for name,relative in FIXED_FILES.items()}
    for name,(directory,filename) in DISCOVERED_FILES.items():
        matches = list((runtime/directory).rglob(filename))
        if len(matches) != 1:
            raise ContractError('MISSION_PACKAGE_TOOL_NOT_UNIQUE:'+name)
        result[name] = str(contained_file(matches[0],name))
    repository = runtime/'maven-repository'
    settings = root/'packaging/rc7/maven-offline-settings.xml'
    if not repository.is_dir() or not settings.is_file():
        raise ContractError('MISSION_PACKAGE_OFFLINE_MAVEN_REQUIRED')
    try:
        repository.resolve().relative_to(runtime)
        settings.resolve().relative_to(root)
    except ValueError:
        raise ContractError('MISSION_PACKAGE_OFFLINE_MAVEN_OUTSIDE_ROOT') from None
    result.update(JAVA_HOME=str(runtime/'java'), MAVEN_HOME=str(runtime/'maven'),
        PFC_MAVEN_REPO=str(repository), PFC_MAVEN_SETTINGS=str(settings),
        MAVEN_ARGS='-o -s "'+str(settings)+'" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local="'+str(repository)+'"')
    directories = []
    for name in ('PFC_NODE_BIN','PFC_BROWSERSKILL_BIN','PFC_RIPGREP_BIN',
                 'PFC_MAVEN_BIN','PFC_JAVA_BIN','PFC_ALLURE_BIN','PFC_K6_BIN','PFC_ZAP_BIN'):
        value = str(Path(result[name]).parent)
        if value not in directories:
            directories.append(value)
    tail = os.environ.get('PATH','') if ambient_path is None else ambient_path
    result['PATH'] = os.pathsep.join(directories + ([tail] if tail else []))
    return result
