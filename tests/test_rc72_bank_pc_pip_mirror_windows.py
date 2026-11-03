"""Real Windows copied-Python test, opt-in only on disposable component runner."""
import base64,hashlib,http.server,json,os,shutil,subprocess,sys,threading,zipfile
from pathlib import Path
import pytest
from rc7_release.bank_pc_pip_mirror_probe import qualify,windows_user_appdata,IMPORT
from rc7_release.package import _bundle_current_windows_python

pytestmark=pytest.mark.skipif(os.name!='nt' or os.environ.get('RC72_PIP_MIRROR_COMPONENT')!='1',
    reason='requires explicitly selected disposable Windows user/mirror runner')


def _wheel(directory):
    name='rc72_bank_mirror_fixture';version='1.0';dist=name+'-'+version+'.dist-info'
    entries={name+'/__init__.py':b'PROOF = "downloaded-from-owned-test-mirror"\n',
        dist+'/METADATA':('Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\n').encode(),
        dist+'/WHEEL':b'Wheel-Version: 1.0\nGenerator: rc72-owned-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
    record=''.join(path+',sha256='+base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')+','+str(len(raw))+'\n' for path,raw in entries.items())
    entries[dist+'/RECORD']=(record+dist+'/RECORD,,\n').encode()
    target=directory/(name+'-'+version+'-py3-none-any.whl');target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,raw in entries.items():archive.writestr(path,raw)
    return target


def test_real_copied_python_mirror_install_import_and_host_substitution_refusals(tmp_path,monkeypatch):
    public=Path(os.environ['RC72_PIP_MIRROR_EVIDENCE']).resolve();public.mkdir(parents=True,exist_ok=True)
    provided=os.environ.get('RC72_PIP_MIRROR_PACKAGE_ROOT')
    if provided:
        root=Path(provided).resolve();archive=Path(os.environ['RC72_PIP_MIRROR_PACKAGE_ARCHIVE']).resolve()
        stage=Path(os.environ['RC72_PIP_MIRROR_ORIGINAL_STAGE']).resolve()
    else:
        stage=tmp_path/'original stage';stage.mkdir();assert _bundle_current_windows_python(stage)
        (stage/'SOURCE_COMMIT').write_text(os.environ['GITHUB_SHA'])
        code=stage/'rc7_release/bank_pc_pip_mirror_probe.py';code.parent.mkdir();shutil.copy2('rc7_release/bank_pc_pip_mirror_probe.py',code)
        archive=tmp_path/'copied-python.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as zipped:
            for path in stage.rglob('*'):
                if path.is_file():zipped.write(path,path.relative_to(stage).as_posix())
        shutil.rmtree(stage);root=tmp_path/'clean package with spaces'
        with zipfile.ZipFile(archive) as zipped:zipped.extractall(root)
    assert not stage.exists()
    wheel=_wheel(tmp_path/'mirror/packages');index=tmp_path/'mirror/simple/rc72-bank-mirror-fixture/index.html';index.parent.mkdir(parents=True)
    index.write_text('<a href="/packages/'+wheel.name+'#sha256='+hashlib.sha256(wheel.read_bytes()).hexdigest()+'">fixture</a>')
    requests=[]
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(tmp_path/'mirror'),**kwargs)
        def do_GET(self):requests.append(self.path);super().do_GET()
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    appdata=windows_user_appdata();config=appdata/'pip/pip.ini';config.parent.mkdir(parents=True,exist_ok=True)
    original=config.read_bytes() if config.exists() else None
    for key in list(os.environ):
        if key.startswith('PIP_'):monkeypatch.delenv(key)
    monkeypatch.setenv('APPDATA',str(appdata));url='http://127.0.0.1:'+str(server.server_port)+'/simple'
    config.write_text('[global]\nindex-url = '+url+'\ntrusted-host = 127.0.0.1\n',encoding='utf-8')
    policy=dict(spec='rc72_bank_mirror_fixture==1.0',module='rc72_bank_mirror_fixture')
    private=tmp_path/'private field proof';negatives=[]
    def refused(name,pattern,**kwargs):
        with pytest.raises(RuntimeError,match=pattern):qualify(root,archive,kwargs.get('policy',policy),private/name,engineering=True)
        negatives.append(name)
    try:
        positive=qualify(root,archive,policy,private/'positive',engineering=True)
        assert positive['status']=='PASS' and positive['bank_pc_mirror_field_fact'] is False
        assert positive['import_proof']['version']=='1.0'
        assert any(p.startswith('/packages/') for p in requests) and any(p.startswith('/simple/') for p in requests)
        (public/'actual-user-mirror-positive.json').write_text(json.dumps(positive,indent=2))
        monkeypatch.setenv('APPDATA',str(tmp_path/'isolated worker appdata'))
        refused('hidden-user-appdata','APPDATA_HIDDEN')
        bridge=qualify(root,archive,policy,private/'explicit-bridge',bridge=True,engineering=True)
        assert bridge['discovery']['mode']=='EXPLICIT_REAL_USER_CONFIG_BRIDGE'
        (public/'actual-user-mirror-bridge.json').write_text(json.dumps(bridge,indent=2))
        monkeypatch.setenv('APPDATA',str(appdata));monkeypatch.setenv('PIP_CONFIG_FILE','NUL')
        refused('null-config-override','CONFIG_OVERRIDE');monkeypatch.delenv('PIP_CONFIG_FILE')
        monkeypatch.setenv('PIP_INDEX_URL','https://unapproved.invalid/simple')
        before=len(requests);refused('wrong-effective-index','EFFECTIVE_INDEX_MISMATCH');assert len(requests)==before
        monkeypatch.delenv('PIP_INDEX_URL')
        refused('missing-mirror-dependency','COMMAND_FAILED:mirror-install',policy=dict(policy,spec='rc72_missing_from_mirror==1.0'))
        # A successful host pip command cannot stand in for broken package pip.
        host=tmp_path/'host bin';host.mkdir();hostpip=host/'pip.cmd';hostpip.write_text('@exit /b 0\n')
        assert subprocess.run([os.environ['COMSPEC'],'/d','/c',str(hostpip)],capture_output=True).returncode==0
        monkeypatch.setenv('PATH',str(host)+os.pathsep+os.environ.get('PATH',''))
        pip=root/'workspace-template/runtime/python/Lib/site-packages/pip';backup=pip.with_name('pip-disabled-for-negative')
        pip.rename(backup)
        try:refused('host-pip-success-package-pip-missing','COMMAND_FAILED:pip-version')
        finally:backup.rename(pip)
        # Even a matching target distribution label cannot bless a host module.
        target=tmp_path/'owned empty import target';target.mkdir();dist=target/'rc72_host_only-1.0.dist-info';dist.mkdir()
        (dist/'METADATA').write_text('Metadata-Version: 2.1\nName: rc72_host_only\nVersion: 1.0\n')
        hostmodule=root/'workspace-template/runtime/python/Lib/site-packages/rc72_host_only.py';hostmodule.write_text('HOST_ONLY=True\n')
        executable=root/'workspace-template/runtime/python/python.exe'
        actual=subprocess.run([str(executable),'-s','-c',IMPORT,str(target),'rc72_host_only','rc72_host_only'],capture_output=True,text=True)
        hostmodule.unlink()
        assert actual.returncode!=0 and 'ValueError' in actual.stderr;negatives.append('host-site-import-refused')
        (public/'actual-negative-summary.json').write_text(json.dumps(dict(status='PASS',negative_checks=negatives,
            actual_mirror_requests=len(requests),full_transport_extraction=bool(provided),original_staging_deleted=not stage.exists(),
            source_commit=os.environ['GITHUB_SHA'],engineering_only=True,field_verified=False,bank_final=False),indent=2))
    finally:
        if original is None:config.unlink(missing_ok=True)
        else:config.write_bytes(original)
        server.shutdown();server.server_close();thread.join(timeout=5)
