"""Actual field requires Windows; these contract tests cover refusal/bridging."""
import json
from pathlib import Path
import pytest
from rc7_release.bank_pc_pip_mirror_probe import prepare_environment,validate_provenance,qualify


def _config(tmp_path):
    app=tmp_path/'real user appdata';config=app/'pip/pip.ini';config.parent.mkdir(parents=True)
    config.write_text('[global]\nindex-url = https://approved.invalid/simple\ntrusted-host = approved.invalid\n')
    return app,config


def test_preserve_real_user_discovery_and_enterprise_settings_without_copying(tmp_path):
    app,config=_config(tmp_path)
    original=dict(APPDATA=str(app),USERPROFILE='real-user',PIP_CERT='enterprise.pem',PYTHONPATH='host-injection')
    values,path,proof=prepare_environment(app,original)
    assert values['APPDATA']==str(app) and values['USERPROFILE']=='real-user' and values['PIP_CERT']=='enterprise.pem'
    assert 'PYTHONPATH' not in values and 'PIP_CONFIG_FILE' not in values and path==config
    assert proof['mode']=='WINDOWS_USER_DISCOVERY' and original['PYTHONPATH']=='host-injection'


def test_hidden_appdata_and_suppressing_config_fail_without_audited_bridge(tmp_path):
    app,config=_config(tmp_path)
    with pytest.raises(RuntimeError,match='APPDATA_HIDDEN'):prepare_environment(app,dict(APPDATA=str(tmp_path/'worker')))
    for value in ['NUL',str(tmp_path/'empty.ini'),str(config)]:
        with pytest.raises(RuntimeError,match='CONFIG_OVERRIDE'):prepare_environment(app,dict(APPDATA=str(app),PIP_CONFIG_FILE=value))
    values,path,proof=prepare_environment(app,dict(APPDATA=str(tmp_path/'worker')),bridge=True)
    assert values['PIP_CONFIG_FILE']==str(config) and proof['mode']=='EXPLICIT_REAL_USER_CONFIG_BRIDGE'
    with pytest.raises(RuntimeError,match='UNAPPROVED_CONFIG_OVERRIDE'):
        prepare_environment(app,dict(APPDATA=str(app),PIP_CONFIG_FILE='NUL'),bridge=True)


def _proof(tmp_path,config):
    runtime=tmp_path/'package/python';python=runtime/'python.exe'
    return python,runtime,dict(executable=str(python),prefix=str(runtime),pip_module=str(runtime/'Lib/site-packages/pip/__init__.py'),
        considered_files={'user':[dict(path=str(config),exists=True)]},loaded_values={'user':{'global.index-url':'https://approved.invalid/simple'}},
        effective=dict(index_url='https://approved.invalid/simple',extra_index_urls=[],trusted_hosts=['approved.invalid'],no_index=False,find_links=[]))


@pytest.mark.parametrize('change',['host-python','host-pip','wrong-index','public-fallback','no-user-discovery','no-user-consumption','trusted-host'])
def test_host_pip_or_environment_success_cannot_replace_user_config_provenance(tmp_path,change):
    app,config=_config(tmp_path);python,runtime,proof=_proof(tmp_path,config)
    if change=='host-python':proof['executable']=str(tmp_path/'host/python.exe')
    elif change=='host-pip':proof['pip_module']=str(tmp_path/'host/pip/__init__.py')
    elif change=='wrong-index':proof['effective']['index_url']='https://public.invalid/simple'
    elif change=='public-fallback':proof['effective']['extra_index_urls']=['https://public.invalid/simple']
    elif change=='no-user-discovery':proof['considered_files']['user']=[]
    elif change=='trusted-host':proof['effective']['trusted_hosts']=[]
    else:proof['loaded_values']['user']={}
    with pytest.raises(RuntimeError):validate_provenance(proof,python,runtime,config,{'approved_index_url':'https://approved.invalid/simple'},False)


def test_missing_package_python_never_consults_host_pip(tmp_path,monkeypatch):
    monkeypatch.setenv('PATH',str(tmp_path/'successful-host-pip'))
    with pytest.raises(RuntimeError,match='PACKAGE_PYTHON_REQUIRED'):qualify(tmp_path/'package',tmp_path/'archive',{},tmp_path/'proof')


@pytest.mark.parametrize('changed',[None,'source','python','pip','probe'])
def test_archive_binding_refuses_other_source_or_replaced_runtime(tmp_path,changed):
    import shutil,zipfile
    from rc7_release import bank_pc_pip_mirror_probe as module
    root=tmp_path/'package';python=root/module.RELATIVE_PYTHON;python.parent.mkdir(parents=True)
    python.write_bytes(b'contract fixture only, no executable claim')
    pip=python.parent/'Lib/site-packages/pip/__init__.py';pip.parent.mkdir(parents=True);pip.write_text('# fixture')
    probe=root/'rc7_release/bank_pc_pip_mirror_probe.py';probe.parent.mkdir();shutil.copy2(module.__file__,probe)
    (root/'SOURCE_COMMIT').write_text('1'*40)
    archive=tmp_path/'package.zip'
    with zipfile.ZipFile(archive,'w') as zipped:
        for path in root.rglob('*'):
            if path.is_file():zipped.write(path,'wrapped/'+path.relative_to(root).as_posix())
    if changed:
        target={'source':root/'SOURCE_COMMIT','python':python,'pip':pip,'probe':probe}[changed];target.write_text('changed')
        with pytest.raises(RuntimeError):module.verify_archive_binding(root,archive,python,pip)
    else:assert len(module.verify_archive_binding(root,archive,python,pip)['files_sha256'])==3


@pytest.mark.parametrize('inputs',[dict(bank_field=True),dict(archive='transport.zip'),dict(bank_pip_field_config='field.json')])
def test_clean_unpack_field_request_cannot_omit_mirror_gate_configuration(tmp_path,inputs):
    from rc7_release.rc72_windows_clean_qualification import qualify
    result=qualify(tmp_path,**inputs)
    assert result['status']=='FAIL' and result['reason']=='BANK_PC_PIP_MIRROR_GATE_CONFIGURATION_REQUIRED'
    assert result['bank_pc_pip_mirror_gate']['status']=='NOT_RUN' and result['field_verified'] is False
