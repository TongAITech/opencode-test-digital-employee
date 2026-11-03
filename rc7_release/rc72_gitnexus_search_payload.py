"""Build-time native FTS acquisition and verified per-worker offline cache copy."""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess,tempfile
from pathlib import Path,PurePosixPath
from rc6_runtime.process_environment import scoped_process_environment

MANIFEST='FTS-PAYLOAD.json'


def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(root):
    root=Path(root).resolve();execution=root/'workspace-template/runtime/node-execution'
    node=root/'workspace-template/runtime/node/node.exe';payload=execution/'fts-payload'
    for path in (node,execution,payload):
        if path.is_symlink():raise RuntimeError('FTS_PACKAGE_PATH_SYMLINK_FORBIDDEN')
        try:path.resolve().relative_to(root)
        except ValueError:raise RuntimeError('FTS_PACKAGE_PATH_OUTSIDE_ROOT') from None
    return node,execution,payload


def _core_version(execution):
    path=execution/'node_modules/@ladybugdb/core/package.json'
    if path.is_symlink():raise RuntimeError('FTS_PACKAGE_CORE_SYMLINK_FORBIDDEN')
    path.resolve().relative_to(execution.resolve())
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('name')!='@ladybugdb/core' or not isinstance(data.get('version'),str):
        raise RuntimeError('FTS_PACKAGE_NATIVE_CORE_REQUIRED')
    return data['version']


def acquire(root,evidence):
    node,execution,payload=_paths(root);evidence=Path(evidence).resolve();evidence.mkdir(parents=True,exist_ok=True)
    installer=execution/'node_modules/gitnexus/scripts/install-duckdb-extension.mjs'
    if not node.is_file() or not installer.is_file():raise RuntimeError('FTS_PACKAGE_INSTALLER_REQUIRED')
    core=_core_version(execution)
    if payload.exists():raise RuntimeError('FTS_PAYLOAD_ALREADY_EXISTS')
    # The actual native installer resolves its own matching extension version.
    # No current-upstream artifact is substituted for a different published core.
    with tempfile.TemporaryDirectory(prefix='rc72-fts-build-') as tmp:
        home=Path(tmp)/'home';home.mkdir()
        env=scoped_process_environment({'GITNEXUS_LBUG_EXTENSION_INSTALL':'auto'},home=home)
        completed=subprocess.run([str(node),str(installer),'fts','1073741824'],cwd=str(execution),env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=120)
        (evidence/'fts-install.stdout.log').write_text(completed.stdout,encoding='utf-8')
        (evidence/'fts-install.stderr.log').write_text(completed.stderr,encoding='utf-8')
        if completed.returncode:raise RuntimeError('FTS_NATIVE_INSTALL_FAILED:'+completed.stderr[-2000:])
        files=sorted(p for p in home.rglob('*') if p.is_file() and p.suffix in {'.lbug_extension','.kuzu_extension'})
        if not files:raise RuntimeError('FTS_NATIVE_INSTALL_DID_NOT_POPULATE_PRIVATE_HOME')
        rows=[]
        for path in files:
            if path.is_symlink() or 'fts' not in str(path.relative_to(home)).lower():
                raise RuntimeError('FTS_NATIVE_INSTALL_UNEXPECTED_ARTIFACT')
            target=payload/'home'/path.relative_to(home);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            rows.append(dict(path=target.relative_to(payload).as_posix(),sha256=_sha(target),bytes=target.stat().st_size))
        manifest=dict(schema='RC72_GITNEXUS_FTS_PAYLOAD_V1',core_version=core,files=rows,
            source='PACKAGED_MATCHING_NATIVE_INSTALLER_AT_BUILD_TIME',offline_execution_qualified=False)
        (payload/MANIFEST).write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return manifest


def restore(root,home):
    _,execution,payload=_paths(root);home=Path(home).resolve()
    manifest=json.loads((payload/MANIFEST).read_text(encoding='utf-8'))
    if (manifest.get('schema')!='RC72_GITNEXUS_FTS_PAYLOAD_V1' or manifest.get('core_version')!=_core_version(execution)
            or not isinstance(manifest.get('files'),list) or not manifest['files']):
        raise RuntimeError('FTS_PAYLOAD_IDENTITY_INVALID')
    rows=[];seen=set()
    for row in manifest['files']:
        value=row.get('path');relative=PurePosixPath(value) if isinstance(value,str) else None
        if (not relative or relative.is_absolute() or '\\' in value or ':' in value or '..' in relative.parts
                or relative.parts[0]!='home' or len(relative.parts)<2 or value in seen
                or relative.suffix not in {'.lbug_extension','.kuzu_extension'}):
            raise RuntimeError('FTS_PAYLOAD_PATH_INVALID')
        seen.add(value);source=payload/relative;target=home/Path(*relative.parts[1:])
        if source.is_symlink() or not source.is_file() or not source.stat().st_size:
            raise RuntimeError('FTS_PAYLOAD_ARTIFACT_REQUIRED')
        source.resolve().relative_to(payload.resolve())
        if _sha(source)!=row.get('sha256') or source.stat().st_size!=row.get('bytes'):
            raise RuntimeError('FTS_PAYLOAD_ARTIFACT_CHANGED')
        # Validate all source and destination paths before copying any file.
        target.resolve().relative_to(home)
        rows.append((source,target))
    for source,target in rows:
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    return manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package-root',required=True);parser.add_argument('--evidence-root',required=True)
    args=parser.parse_args();out=Path(args.evidence_root);out.mkdir(parents=True,exist_ok=True)
    try:result=dict(status='ACQUIRED',payload=acquire(args.package_root,out),offline_execution_qualified=False)
    except Exception as exc:result=dict(status='FAIL',error=str(exc),error_type=type(exc).__name__,offline_execution_qualified=False)
    (out/'fts-acquisition.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(result,sort_keys=True));return 0 if result['status']=='ACQUIRED' else 1


if __name__=='__main__':raise SystemExit(main())
