"""Physical full-transport inventory, not product or bank acceptance authority."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from .runtime_delivery_contract import verify_runtime_delivery,verify_turnkey_npm_package
from .package import _is_runtime_generated

GROUPS=('python','node','node-execution','browser','code-intelligence','java','maven','maven-repository',
        'allure','k6','zap','ripgrep','dsh-plugins')
INVENTORY='FULL-CAPABILITY-INVENTORY.json'


def build_inventory(root):
    root=Path(root).resolve()
    commit=(root/'SOURCE_COMMIT').read_text(encoding='utf-8').strip()
    if not re.fullmatch('[0-9a-fA-F]{40}',commit):raise RuntimeError('RC72_COMPLETE_PAYLOAD_SOURCE_REQUIRED')
    if (root/'RELEASE_FAMILY').read_text(encoding='utf-8').strip()!='RC7.2':raise RuntimeError('RC72_COMPLETE_PAYLOAD_IDENTITY_REQUIRED')
    delivery=verify_runtime_delivery(root)
    rows=[]
    for name in GROUPS:
        directory=root/'workspace-template/runtime'/name
        files=[p for p in directory.rglob('*') if p.is_file() and not _is_runtime_generated(root,p)] if directory.is_dir() else []
        if not files or not any(p.stat().st_size for p in files):raise RuntimeError('RC72_COMPLETE_PAYLOAD_GROUP_MISSING:'+name)
        rows.append(dict(group=name,relative_root=directory.relative_to(root).as_posix(),files=len(files),bytes=sum(p.stat().st_size for p in files)))
    # The RC7.1 reference carried this optional secondary provider physically.
    # Disabling runtime activation cannot silently turn a full package into lite.
    graph=verify_turnkey_npm_package(root/'workspace-template/runtime/node-execution/node_modules/gitnexus','gitnexus')
    if graph['status']!='PASS':raise RuntimeError('RC72_COMPLETE_GITNEXUS_REQUIRED:'+str(graph.get('reason')))
    from .rc72_gitnexus_search_payload import validate_payload
    fts_payload=validate_payload(root)
    bundles=[]
    for item in delivery['turnkey_bundles']:
        item=dict(item)
        if item.get('archive'):item['archive']=Path(item['archive']).resolve().relative_to(root).as_posix()
        bundles.append(item)
    return dict(schema='RC72_FULL_PHYSICAL_PAYLOAD_V1',source_commit=commit,release_family='RC7.2',status='PASS',
        qualification_scope='PHYSICAL_INVENTORY_ONLY',field_verified=False,bank_final=False,
        independent_execution_qualification_required=True,durable_truth='R1_EVENT_STREAM',
        file_integrity_authority='PACKAGE_MANIFEST.json_AND_CHECKSUMS.sha256',groups=rows,
        gitnexus=dict(graph,runtime_required=False,default_enabled=False,physically_carried=True,change_truth_authority=False),
        native_fts_payload=fts_payload,turnkey_optional_bundles=bundles)


def write_inventory(root):
    root=Path(root).resolve();payload=build_inventory(root)
    (root/INVENTORY).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return payload


def verify_inventory(root):
    root=Path(root).resolve()
    try:stored=json.loads((root/INVENTORY).read_text(encoding='utf-8'))
    except (ValueError,OSError) as exc:raise RuntimeError('RC72_COMPLETE_PAYLOAD_INVENTORY_REQUIRED') from exc
    if stored!=build_inventory(root):raise RuntimeError('RC72_COMPLETE_PAYLOAD_INVENTORY_CHANGED')
    return stored


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package-root',required=True)
    args=parser.parse_args()
    try:result=verify_inventory(args.package_root)
    except Exception as exc:
        print(json.dumps(dict(status='FAIL',error=str(exc),qualification_scope='PHYSICAL_INVENTORY_ONLY')));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
