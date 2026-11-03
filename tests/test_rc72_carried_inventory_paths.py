"""Actual archive layouts, physical presence only, no Field qualification."""
import os
import pytest
from rc7_release.final_unified_overlay import build_inventory

LAYOUT={
    'K6':'k6/k6-v2.3.0-windows-amd64/k6.exe',
    'ALLURE_CLI':'allure/allure-2.46.1/bin/allure.bat',
    'ZAP':'zap/ZAP_2.17.0/zap.bat',
}


def _paths(root):
    for relative in LAYOUT.values():
        path=root/'workspace-template/runtime'/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'physical presence fixture only')


def test_versioned_archive_tools_have_exact_carried_paths_without_field_promotion(tmp_path):
    _paths(tmp_path)
    result=build_inventory(tmp_path,'a'*40)
    tools={r['id']:r for r in result['capabilities']}
    for name,path in LAYOUT.items():
        assert tools[name]['status']=='BUNDLED_ENABLED'
        assert tools[name]['path']=='workspace-template/runtime/'+path
    assert result['real_bank_mission']=='HOLD_FIELD_EVIDENCE_REQUIRED'


@pytest.mark.parametrize('tool',list(LAYOUT))
@pytest.mark.parametrize('change',['missing','ambiguous','symlink'])
def test_missing_ambiguous_or_outside_tool_cannot_be_reported_bundled(tmp_path,tool,change):
    if change=='symlink' and os.name=='nt':pytest.skip('Windows symlink privilege is host dependent')
    _paths(tmp_path)
    path=tmp_path/'workspace-template/runtime'/LAYOUT[tool]
    if change=='missing':path.unlink()
    elif change=='ambiguous':
        other=path.parent/'extra'/path.name
        other.parent.mkdir();other.write_bytes(b'conflicting version')
    else:
        outside=tmp_path/'outside';outside.write_bytes(b'host replacement')
        path.unlink();path.symlink_to(outside)
    tools={r['id']:r for r in build_inventory(tmp_path,'a'*40)['capabilities']}
    assert tools[tool]['status']=='MISSING' and tools[tool].get('path') is None
