"""Private authority must stay private even if a key happens to be UTF-8."""
import os
import pytest
from rc7_release.source_tools import read_text, SourceToolError
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource


@pytest.mark.parametrize('scope',['workspace','state'])
def test_controller_key_cannot_be_read_through_generic_or_native_source_tools(tmp_path,monkeypatch,scope):
    directory=tmp_path/'mission-owned/authority';directory.mkdir(parents=True)
    key=directory/'controller.key';key.write_text('private-signing-material-12345678')
    monkeypatch.setenv('PFC_WORKSPACE',str(tmp_path))
    monkeypatch.setenv('PFC_AITEST_STATE_DIR',str(tmp_path))
    with pytest.raises(SourceToolError,match='CONTROLLER_SECRET_FORBIDDEN'):
        read_text(path=key.relative_to(tmp_path).as_posix(),scope=scope)
    with pytest.raises(ContractError,match='CONTROL_SECRET_FORBIDDEN'):
        N1ReadResource('source://must-not-promote-control-material',key)
    source=tmp_path/'approved-input.txt';source.write_text('ordinary approved input')
    assert read_text(path=source.name,scope=scope)['text']=='ordinary approved input'
    assert N1ReadResource('source://original',source).path==source.resolve()


@pytest.mark.skipif(os.name=='nt',reason='symlink creation is host-policy dependent on Windows')
def test_renamed_symlink_cannot_hide_private_controller_path(tmp_path,monkeypatch):
    directory=tmp_path/'authority';directory.mkdir()
    key=directory/'controller.key';key.write_text('private-signing-material-12345678')
    link=tmp_path/'apparently-ordinary-source.txt';link.symlink_to(key)
    monkeypatch.setenv('PFC_WORKSPACE',str(tmp_path))
    with pytest.raises(SourceToolError,match='CONTROLLER_SECRET_FORBIDDEN'):
        read_text(path=link.name)
