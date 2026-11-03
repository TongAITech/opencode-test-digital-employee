"""Relocated native extension cache integrity; actual Windows loads run in CI."""
import hashlib,json,shutil
from pathlib import Path
import pytest
from rc7_release.rc72_gitnexus_search_payload import restore


def _payload(root):
    execution=root/'workspace-template/runtime/node-execution'
    core=execution/'node_modules/@ladybugdb/core/package.json';core.parent.mkdir(parents=True)
    core.write_text(json.dumps(dict(name='@ladybugdb/core',version='0.fixture')))
    payload=execution/'fts-payload';artifact=payload/'home/.lbdb/extension/0.fixture/fts/libfts.lbug_extension'
    artifact.parent.mkdir(parents=True);artifact.write_bytes(b'fixture bytes, not native qualification')
    manifest=dict(schema='RC72_GITNEXUS_FTS_PAYLOAD_V1',core_version='0.fixture',files=[dict(
        path=artifact.relative_to(payload).as_posix(),sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),bytes=artifact.stat().st_size)])
    path=payload/'FTS-PAYLOAD.json';path.write_text(json.dumps(manifest));return path,artifact,manifest


def test_restore_after_original_removed_preserves_only_manifested_extension(tmp_path):
    stage=tmp_path/'stage';path,artifact,manifest=_payload(stage)
    (path.parent/'home/secret-not-an-extension').write_text('must not travel')
    clean=tmp_path/'clean package';shutil.copytree(stage,clean);shutil.rmtree(stage)
    home=tmp_path/'worker private home';assert restore(clean,home)==manifest
    assert len(list(home.rglob('*.lbug_extension')))==1
    assert not (home/'secret-not-an-extension').exists()


@pytest.mark.parametrize('change',['tamper','version','escape','missing'])
def test_corrupt_or_wrong_core_cache_refused_before_any_copy(tmp_path,change):
    root=tmp_path/'package';path,artifact,manifest=_payload(root)
    if change=='tamper':artifact.write_bytes(b'corrupt')
    elif change=='missing':artifact.unlink()
    elif change=='version':manifest['core_version']='other'
    else:manifest['files'][0]['path']='home/../../outside.lbug_extension'
    path.write_text(json.dumps(manifest));home=tmp_path/'private'
    with pytest.raises(RuntimeError):restore(root,home)
    assert not home.exists()


def test_external_payload_symlink_is_not_transportable(tmp_path):
    root=tmp_path/'package';path,artifact,manifest=_payload(root)
    external=tmp_path/'external';shutil.move(str(path.parent),external)
    path.parent.symlink_to(external,target_is_directory=True)
    with pytest.raises(RuntimeError,match='SYMLINK'):restore(root,tmp_path/'private')
