"""Complete physical groups cannot be inferred from a weakened runtime lock."""
import json,shutil
import pytest
from test_rc7_runtime_delivery_contract import _full_layout,_write_json
from rc7_release.rc72_complete_payload_inventory import GROUPS,build_inventory,write_inventory,verify_inventory


def _layout(root):
    _full_layout(root)
    (root/'SOURCE_COMMIT').write_text('1'*40);(root/'RELEASE_FAMILY').write_text('RC7.2')
    for name in GROUPS:
        path=root/'workspace-template/runtime'/name/'fixture.payload';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'physical fixture, not capability proof')
    package=root/'workspace-template/runtime/node-execution/node_modules/gitnexus'
    _write_json(package/'package.json',dict(name='gitnexus',version='fixture',bin=dict(gitnexus='dist/cli.js')))
    cli=package/'dist/cli.js';cli.parent.mkdir();cli.write_text('// fixture CLI')
    from test_rc72_gitnexus_search_payload import _payload
    _payload(root)


def test_complete_inventory_moves_with_package_and_still_requires_independent_execution(tmp_path):
    root=tmp_path/'stage';_layout(root);original=write_inventory(root)
    clean=tmp_path/'clean package';shutil.copytree(root,clean);shutil.rmtree(root)
    assert verify_inventory(clean)==original
    assert original['independent_execution_qualification_required'] is True
    assert original['qualification_scope']=='PHYSICAL_INVENTORY_ONLY' and original['bank_final'] is False
    assert len(original['groups'])==13
    extra=clean/'workspace-template/runtime/java/new-file';extra.write_bytes(b'extra')
    with pytest.raises(RuntimeError,match='INVENTORY_CHANGED'):verify_inventory(clean)


def test_ordinary_optional_flag_cannot_omit_inherited_gitnexus_from_complete_inventory(tmp_path):
    _layout(tmp_path);shutil.rmtree(tmp_path/'workspace-template/runtime/node-execution/node_modules/gitnexus')
    with pytest.raises(RuntimeError,match='COMPLETE_GITNEXUS_REQUIRED'):build_inventory(tmp_path)


def test_required_group_cannot_disappear_behind_an_incomplete_lock(tmp_path):
    _layout(tmp_path);shutil.rmtree(tmp_path/'workspace-template/runtime/java')
    with pytest.raises(RuntimeError,match='GROUP_MISSING:java'):build_inventory(tmp_path)


def test_full_transport_requires_native_search_payload_not_just_graph_cli(tmp_path):
    _layout(tmp_path)
    (tmp_path/'workspace-template/runtime/node-execution/fts-payload/FTS-PAYLOAD.json').unlink()
    with pytest.raises(RuntimeError,match='FTS_PAYLOAD_MANIFEST_REQUIRED'):build_inventory(tmp_path)
