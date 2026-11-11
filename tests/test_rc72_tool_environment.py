"""Path-selection fixtures only; actual binaries are qualified in full Windows CI."""
import os
from pathlib import Path
import pytest
from rc7_runtime.models import ContractError
from rc7_release.rc72_tool_environment import FIXED_FILES, package_tool_environment


def _paths(root):
    root.mkdir(exist_ok=True)
    (root/'PACKAGE_MANIFEST.json').write_text('{}')
    runtime=root/'workspace-template/runtime'
    for relative in list(FIXED_FILES.values())+['allure/version/bin/allure.bat','k6/k6-v-test/k6.exe','zap/version/zap.bat']:
        file=runtime/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'path-selection fixture')
    (runtime/'maven-repository').mkdir()
    settings=root/'packaging/rc7/maven-offline-settings.xml';settings.parent.mkdir(parents=True);settings.write_text('<settings/>')
    return runtime


def test_all_carried_tools_bind_to_current_extraction_and_precede_host_path(tmp_path):
    root=tmp_path/'package with spaces 中文';runtime=_paths(root)
    environment=package_tool_environment(root,ambient_path='approved-host-path')
    for name,relative in FIXED_FILES.items():assert environment[name]==str((runtime/relative).resolve())
    assert environment['PFC_K6_BIN']==str((runtime/'k6/k6-v-test/k6.exe').resolve())
    assert environment['PATH'].split(os.pathsep)[0]==str(runtime/'node')
    assert environment['PATH'].split(os.pathsep)[-1]=='approved-host-path'
    assert environment['JAVA_HOME']==str(runtime/'java')
    assert '-o -s "'+str(root/'packaging/rc7/maven-offline-settings.xml')+'"' in environment['MAVEN_ARGS']
    assert str(runtime/'maven-repository') in environment['MAVEN_ARGS']


@pytest.mark.parametrize('mutation,reason',[('missing','TOOL_REQUIRED'),('ambiguous','TOOL_NOT_UNIQUE'),('maven','OFFLINE_MAVEN_REQUIRED')])
def test_full_package_never_substitutes_a_host_tool_when_carried_binding_is_missing(tmp_path,mutation,reason):
    root=tmp_path/'package';runtime=_paths(root)
    if mutation=='missing':(runtime/FIXED_FILES['PFC_CODEGRAPH_BIN']).unlink()
    elif mutation=='ambiguous':
        path=runtime/'zap/other/zap.bat';path.parent.mkdir();path.write_text('second candidate')
    else:(root/'packaging/rc7/maven-offline-settings.xml').unlink()
    with pytest.raises(ContractError,match=reason):package_tool_environment(root,ambient_path='host-tool-path')


@pytest.mark.skipif(os.name=='nt',reason='symlink creation depends on Windows host policy')
def test_carried_tool_cannot_escape_through_parent_directory_symlink(tmp_path):
    root=tmp_path/'package';runtime=_paths(root)
    binary=runtime/FIXED_FILES['PFC_CODEGRAPH_BIN'];binary.unlink()
    outside=tmp_path/'host-binary.exe';outside.write_bytes(b'not the carried tool')
    binary.symlink_to(outside)
    with pytest.raises(ContractError,match='OUTSIDE_RUNTIME|SYMLINK'):package_tool_environment(root)


def test_component_has_no_implied_full_runtime_projection(tmp_path):
    assert package_tool_environment(tmp_path)=={}
