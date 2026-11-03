"""Actual package-Python/user-config/mirror-install proof; never host pip proof."""
from __future__ import annotations
import argparse,configparser,ctypes,hashlib,json,os,re,subprocess,time,uuid,zipfile
from pathlib import Path
from urllib.parse import urlsplit

RELATIVE_PYTHON=Path('workspace-template/runtime/python/python.exe')
GATE='BANK_PC_PIP_MIRROR_GATE'


def _sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def windows_user_appdata():
    if os.name!='nt':raise RuntimeError('PIP_MIRROR_WINDOWS_USER_REQUIRED')
    buffer=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,26,None,0,buffer)!=0 or not buffer.value:
        raise RuntimeError('PIP_MIRROR_WINDOWS_USER_PROFILE_UNAVAILABLE')
    return Path(buffer.value).resolve()


def prepare_environment(real_appdata,ambient,*,bridge=False):
    """Preserve real user settings, or explicitly bridge their original file.

    real_appdata comes from the Windows known-folder API, independent of an
    isolated worker's substituted APPDATA. No bank config is copied or edited.
    """
    real_appdata=Path(real_appdata).resolve();config=real_appdata/'pip/pip.ini'
    if config.is_symlink() or not config.is_file():raise RuntimeError('PIP_MIRROR_REAL_USER_CONFIG_REQUIRED')
    values=dict(ambient)
    actual=values.get('APPDATA')
    changed=not actual or Path(actual).resolve()!=real_appdata
    override=values.get('PIP_CONFIG_FILE')
    if not bridge and changed:raise RuntimeError('PIP_MIRROR_USER_APPDATA_HIDDEN')
    if not bridge and override:raise RuntimeError('PIP_MIRROR_CONFIG_OVERRIDE_FORBIDDEN')
    if bridge:
        if override and Path(override).resolve()!=config.resolve():
            raise RuntimeError('PIP_MIRROR_UNAPPROVED_CONFIG_OVERRIDE')
        values['PIP_CONFIG_FILE']=str(config)
    for key in tuple(values):
        if key.upper() in {'PYTHONHOME','PYTHONPATH','PYTHONSTARTUP','PYTHONINSPECT'}:values.pop(key)
    values['PYTHONNOUSERSITE']='1';values['PYTHONDONTWRITEBYTECODE']='1'
    return values,config,dict(mode='EXPLICIT_REAL_USER_CONFIG_BRIDGE' if bridge else 'WINDOWS_USER_DISCOVERY',
        real_appdata=str(real_appdata),effective_appdata=actual,user_config=str(config),user_config_sha256=_sha(config))


PROVENANCE=r'''import json,sys,pip
from pathlib import Path
from pip._internal.configuration import Configuration
from pip._internal.commands import create_command
configuration=Configuration(isolated=False);configuration.load()
options,arguments=create_command('install',isolated=False).parse_args([])
def loaded_values(parsers):
    values={}
    for filename,parser in parsers:
        for section in parser.sections():
            for name,value in parser.items(section):values[section+'.'+name.lower().replace('_','-')]=value
    return values
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,
 pip_version=pip.__version__,pip_module=str(Path(pip.__file__).resolve()),
 considered_files={str(k):[dict(path=f,exists=Path(f).is_file()) for f in files] for k,files in configuration.iter_config_files()},
 loaded_values={str(k):loaded_values(v) for k,v in configuration._parsers.items()},
 effective=dict(index_url=options.index_url,extra_index_urls=options.extra_index_urls,
 trusted_hosts=options.trusted_hosts,no_index=options.no_index,find_links=options.find_links))))
'''
IMPORT=r'''import importlib,importlib.metadata,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();module_name=sys.argv[2];distribution=sys.argv[3]
sys.path.insert(0,str(root))
canonical=lambda value:re.sub(r'[-_.]+','-',value).lower()
dists=[d for d in importlib.metadata.distributions(path=[str(root)]) if canonical(d.metadata['Name'])==canonical(distribution)]
assert len(dists)==1,'PIP_MIRROR_TARGET_DISTRIBUTION_REQUIRED'
module=importlib.import_module(module_name)
locations=[str(Path(module.__file__).resolve())] if getattr(module,'__file__',None) else [str(Path(p).resolve()) for p in module.__path__]
assert locations,'PIP_MIRROR_IMPORTED_LOCATION_REQUIRED'
for location in locations:Path(location).relative_to(root)
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,distribution=dists[0].metadata['Name'],
 version=dists[0].version,distribution_root=str(Path(dists[0].locate_file('')).resolve()),module=module_name,locations=locations)))
'''


def _origin(url):
    parsed=urlsplit(url)
    if parsed.scheme not in {'https','http'} or not parsed.hostname or parsed.fragment:
        raise RuntimeError('PIP_MIRROR_APPROVED_NETWORK_INDEX_REQUIRED')
    return parsed.scheme,parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)


def _json(text):
    try:value=json.loads(text)
    except ValueError:raise RuntimeError('PIP_MIRROR_CHILD_STRUCTURED_RESULT_REQUIRED') from None
    if not isinstance(value,dict):raise RuntimeError('PIP_MIRROR_CHILD_STRUCTURED_RESULT_REQUIRED')
    return value


def _inside(path,root,error):
    try:Path(path).resolve().relative_to(root)
    except (ValueError,TypeError):raise RuntimeError(error) from None


def validate_provenance(proof,python,runtime,config,policy,bridge):
    if Path(proof.get('executable','')).resolve()!=python or Path(proof.get('prefix','')).resolve()!=runtime:
        raise RuntimeError('PIP_MIRROR_PACKAGE_INTERPRETER_REQUIRED')
    _inside(proof.get('pip_module'),runtime,'PIP_MIRROR_PACKAGE_PIP_REQUIRED')
    parser=configparser.RawConfigParser();parser.read(str(config),encoding='utf-8-sig')
    user_index=parser.get('install','index-url',fallback=parser.get('global','index-url',fallback=None))
    approved=policy['approved_index_url']
    if not user_index or user_index.rstrip('/')!=approved.rstrip('/'):
        raise RuntimeError('PIP_MIRROR_APPROVED_USER_INDEX_REQUIRED')
    effective=proof['effective']
    if effective.get('index_url','').rstrip('/')!=approved.rstrip('/') or effective.get('no_index') or effective.get('find_links'):
        raise RuntimeError('PIP_MIRROR_EFFECTIVE_INDEX_MISMATCH')
    expected_extra=parser.get('install','extra-index-url',fallback=parser.get('global','extra-index-url',fallback='')).split()
    if effective.get('extra_index_urls',[])!=expected_extra:
        raise RuntimeError('PIP_MIRROR_UNAPPROVED_EXTRA_INDEX')
    kind='env' if bridge else 'user'
    files=proof.get('considered_files',{}).get(kind,[])
    if not any(row.get('exists') is True and Path(row['path']).resolve()==config.resolve() for row in files):
        raise RuntimeError('PIP_MIRROR_USER_CONFIG_NOT_DISCOVERED')
    loaded=proof.get('loaded_values',{}).get(kind,{})
    if loaded.get('install.index-url',loaded.get('global.index-url','')).rstrip('/')!=approved.rstrip('/'):
        raise RuntimeError('PIP_MIRROR_USER_CONFIG_NOT_CONSUMED')
    trusted=parser.get('install','trusted-host',fallback=parser.get('global','trusted-host',fallback='')).split()
    if effective.get('trusted_hosts',[])!=trusted:raise RuntimeError('PIP_MIRROR_TRUSTED_HOST_SETTINGS_CHANGED')
    _origin(approved)
    return effective


def verify_archive_binding(root,archive,python,pip_module):
    source=(root/'SOURCE_COMMIT').read_bytes()
    relative=[python.relative_to(root).as_posix(),Path(pip_module).relative_to(root).as_posix(),
        'rc7_release/bank_pc_pip_mirror_probe.py']
    if _sha(root/relative[2])!=_sha(Path(__file__).resolve()):
        raise RuntimeError('PIP_MIRROR_EXECUTED_PROBE_OUTSIDE_ARCHIVE_SOURCE')
    with zipfile.ZipFile(archive) as zipped:
        names=zipped.namelist()
        prefixes=[name[:-len('SOURCE_COMMIT')] for name in names if name=='SOURCE_COMMIT' or name.endswith('/SOURCE_COMMIT')]
        prefixes=[prefix for prefix in prefixes if all(prefix+name in names for name in relative)]
        if len(prefixes)!=1:raise RuntimeError('PIP_MIRROR_ARCHIVE_PACKAGE_NOT_UNIQUE')
        prefix=prefixes[0]
        if zipped.read(prefix+'SOURCE_COMMIT')!=source:raise RuntimeError('PIP_MIRROR_ARCHIVE_SOURCE_CHANGED')
        files={}
        for name in relative:
            digest=hashlib.sha256()
            with zipped.open(prefix+name) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            if digest.hexdigest()!=_sha(root/name):raise RuntimeError('PIP_MIRROR_ARCHIVE_RUNTIME_CHANGED')
            files[name]=digest.hexdigest()
    return dict(archive_prefix=prefix,source_commit=source.decode().strip(),files_sha256=files)


def qualify(package_root,archive,policy,evidence_root,*,bridge=False,engineering=False):
    root=Path(package_root).resolve();archive=Path(archive).resolve();evidence=Path(evidence_root).resolve()
    python=root/RELATIVE_PYTHON;runtime=python.parent
    if python.is_symlink() or not python.is_file():raise RuntimeError('PIP_MIRROR_PACKAGE_PYTHON_REQUIRED')
    _inside(python,root,'PIP_MIRROR_PACKAGE_PYTHON_REQUIRED')
    source=(root/'SOURCE_COMMIT').read_text(encoding='utf-8').strip()
    if not re.fullmatch('[0-9a-f]{40}',source):raise RuntimeError('PIP_MIRROR_EXACT_SOURCE_REQUIRED')
    if not archive.is_file():raise RuntimeError('PIP_MIRROR_ARCHIVE_REQUIRED')
    if (not isinstance(policy,dict) or not isinstance(policy.get('spec'),str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~0-9A-Za-z*.,+-]+)?',policy['spec'])
            or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',policy.get('module',''))
            or not isinstance(policy.get('approved_index_url'),str)):
        raise RuntimeError('PIP_MIRROR_FIELD_PACKAGE_POLICY_REQUIRED')
    expected_name=re.match(r'[A-Za-z0-9][A-Za-z0-9_.-]*',policy['spec']).group()
    env,config,discovery=prepare_environment(windows_user_appdata(),os.environ,bridge=bridge)
    evidence.mkdir(parents=True,exist_ok=True);private=evidence/'private';private.mkdir(mode=0o700,exist_ok=True)
    def run(name,args,timeout=90):
        try:completed=subprocess.run([str(python),'-s',*args],cwd=str(runtime),env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        except subprocess.TimeoutExpired:raise RuntimeError('PIP_MIRROR_COMMAND_TIMEOUT:'+name) from None
        for suffix,content in [('stdout',completed.stdout),('stderr',completed.stderr)]:
            path=private/(name+'.'+suffix+'.log');path.write_text(content,encoding='utf-8');path.chmod(0o600)
        if completed.returncode:raise RuntimeError('PIP_MIRROR_COMMAND_FAILED:'+name)
        return completed.stdout
    run('pip-version',['-m','pip','--version'])
    before=_json(run('provenance',['-c',PROVENANCE]));validate_provenance(before,python,runtime,config,policy,bridge)
    archive_binding=verify_archive_binding(root,archive,python,Path(before['pip_module']))
    run('config-debug',['-m','pip','config','debug']);run('config-list',['-m','pip','config','list','-v'])
    if _sha(config)!=discovery['user_config_sha256']:raise RuntimeError('PIP_MIRROR_USER_CONFIG_CHANGED')
    target=root/'state/pip-mirror'/uuid.uuid4().hex
    _inside(target,root,'PIP_MIRROR_OWNED_INSTALL_TARGET_REQUIRED');target.mkdir(parents=True,exist_ok=False)
    report=private/'install-report.json'
    run('mirror-install',['-m','pip','install','--no-input','--disable-pip-version-check','--no-cache-dir','--ignore-installed',
        '--only-binary=:all:','--target',str(target),'--report',str(report),'--timeout','20','--retries','0',policy['spec']],180)
    data=json.loads(report.read_text(encoding='utf-8'));report.chmod(0o600)
    installs=data.get('install',[])
    canonical=lambda name:re.sub(r'[-_.]+','-',name).lower()
    if not installs or not any(canonical(i.get('metadata',{}).get('name',''))==canonical(expected_name) for i in installs):
        raise RuntimeError('PIP_MIRROR_FRESH_DISTRIBUTION_REQUIRED')
    origins={_origin(policy['approved_index_url'])}
    origins.update(_origin(v) for v in policy.get('approved_download_origins',[]))
    for item in installs:
        if _origin(item.get('download_info',{}).get('url','')) not in origins:
            raise RuntimeError('PIP_MIRROR_UNAPPROVED_DOWNLOAD_ORIGIN')
    imported=_json(run('same-interpreter-import',['-c',IMPORT,str(target),policy['module'],expected_name]))
    if Path(imported['executable']).resolve()!=python or Path(imported['prefix']).resolve()!=runtime:
        raise RuntimeError('PIP_MIRROR_IMPORT_INTERPRETER_CHANGED')
    _inside(imported['distribution_root'],target,'PIP_MIRROR_IMPORT_OUTSIDE_TARGET')
    for location in imported['locations']:_inside(location,target,'PIP_MIRROR_IMPORT_OUTSIDE_TARGET')
    if _sha(config)!=discovery['user_config_sha256']:raise RuntimeError('PIP_MIRROR_USER_CONFIG_CHANGED')
    after=_json(run('provenance-after',['-c',PROVENANCE]));validate_provenance(after,python,runtime,config,policy,bridge)
    logs={p.name:_sha(p) for p in private.iterdir() if p.is_file()}
    return dict(gate=GATE,status='PASS',schema='RC72_BANK_PC_PIP_MIRROR_V1',source_commit=source,
        archive_sha256=_sha(archive),archive_binding=archive_binding,package_root=str(root),python_executable=str(python),python_prefix=before['prefix'],
        pip_version=before['pip_version'],pip_module=before['pip_module'],discovery=discovery,
        approved_index_sha256=hashlib.sha256(policy['approved_index_url'].encode()).hexdigest(),
        spec=policy['spec'],installation_target=str(target),import_proof=imported,
        resolved=[dict(name=i['metadata']['name'],version=i['metadata']['version']) for i in installs],
        private_evidence_sha256=logs,observed_at=int(time.time()),
        qualification_scope='ENGINEERING_WINDOWS_USER_MIRROR_SIMULATION' if engineering else 'BANK_PC_USER_MIRROR_FIELD_FACT',
        bank_pc_mirror_field_fact=not engineering,field_verified=False,bank_final=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package-root',required=True);parser.add_argument('--archive',required=True)
    parser.add_argument('--field-config',required=True);parser.add_argument('--evidence-root',required=True)
    parser.add_argument('--bridge-user-config',action='store_true');parser.add_argument('--engineering',action='store_true')
    args=parser.parse_args();evidence=Path(args.evidence_root);evidence.mkdir(parents=True,exist_ok=True)
    try:result=qualify(args.package_root,args.archive,json.loads(Path(args.field_config).read_text(encoding='utf-8')),
        evidence,bridge=args.bridge_user_config,engineering=args.engineering)
    except Exception as exc:result=dict(gate=GATE,status='FAIL',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,RuntimeError) else 'PIP_MIRROR_QUALIFICATION_FAILED',field_verified=False,bank_final=False)
    (evidence/'bank-pc-pip-mirror.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(result,sort_keys=True));return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
