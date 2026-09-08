"""Seal a successful Windows run into the deliverable; code/payload bytes are unchanged."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from closure_contract import REQUIRED_GATES


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--bundle', type=Path, required=True); parser.add_argument('--output', type=Path, required=True); parser.add_argument('--local-report', type=Path)
    args = parser.parse_args(); bundle = args.bundle.resolve(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    machine = json.loads((bundle / 'windows-validation.json').read_text(encoding='utf-8'))
    if machine.get('WINDOWS_CI_PASS') is not True or machine.get('status') != 'PASS':
        raise RuntimeError('Successful Windows payload execution is required before qualification')
    provenance = json.loads((bundle / 'BUILD_PROVENANCE.json').read_text(encoding='utf-8'))
    if machine.get('source_head') != provenance.get('source_head'):
        raise RuntimeError('Validation source HEAD differs from delivered source')
    if os.environ.get('GITHUB_SHA') != provenance.get('source_head'):
        raise RuntimeError('Fresh exact-source Windows workflow is required')
    # Never inherit a historical machine report as evidence for this repair.
    local = json.loads(args.local_report.read_text(encoding='utf-8')) if args.local_report else {
        'source_head': machine['source_head'],
        'LOCAL_VALIDATION_PASS': machine.get('LOCAL_VALIDATION_PASS') is True,
        'scope': 'Current installed packaged-Python contract suites on Windows',
    }
    if local.get('source_head') != provenance['source_head']:
        raise RuntimeError('Local evidence does not match this source HEAD')
    original_checksums = json.loads((bundle / 'FILE_SHA256.json').read_text(encoding='utf-8'))
    for relative, expected in original_checksums.items():
        if sha(bundle / relative) != expected: raise RuntimeError('Source/payload changed during validation: ' + relative)
    proof = {'run_id': os.environ.get('GITHUB_RUN_ID'), 'workflow_head': os.environ.get('GITHUB_SHA'),
             'url': f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}",
             'tested_input_zip_sha256': os.environ.get('AITEST_INPUT_SHA256'),
             'carrier_sha256': os.environ.get('AITEST_CARRIER_SHA256'),
             'carrier_scope': 'OFFLINE_DEPENDENCIES_ONLY; ALL_SOURCE_AND_TESTS_FROM_WORKFLOW_HEAD',
             'installed_runtime': machine.get('installed_runtime_roots'),
             'repack_scope': 'Validation reports and checksums only; original source and payload files verified unchanged before sealing'}
    machine['LOCAL_VALIDATION_PASS'] = local.get('LOCAL_VALIDATION_PASS') is True
    local_label = 'LOCAL_VALIDATION_PASS' if machine['LOCAL_VALIDATION_PASS'] else 'LOCAL_VALIDATION_PENDING_OR_FAILED'
    machine['status'] = 'PASS' if machine['LOCAL_VALIDATION_PASS'] else 'WINDOWS_PASS_LOCAL_PENDING_OR_FAILED'
    machine['local_construction_validation'] = local
    machine['windows_ci'] = proof
    machine['qualification'] = local_label + ' + WINDOWS_CI_PASS; BANK_FIELD_VALIDATION_REQUIRED'
    gates = machine.get('gates', {})
    if not gates: raise RuntimeError('10.REC.3 named gate evidence is missing')
    for gate in REQUIRED_GATES:
        if gate != 'FINAL_ZIP_SEALED': gates.setdefault(gate, 'NOT_PROVEN')
    pending = {key: gates.get(key, 'NOT_PROVEN') for key in REQUIRED_GATES
               if key != 'FINAL_ZIP_SEALED' and gates.get(key) != 'PASS'}
    if not machine['LOCAL_VALIDATION_PASS']:
        pending['LOCAL_CONTRACT_VALIDATION'] = 'NOT_PASS'
    if pending:
        raise RuntimeError('REC3_FINAL_CLOSURE_GATES_NOT_PASS: ' + json.dumps(pending, sort_keys=True))
    gates['FINAL_ZIP_SEALED'] = 'PASS'
    machine['closure'] = 'PASS'
    machine['unproven_closure_gates'] = {}
    write(bundle / 'MACHINE_VALIDATION_RESULT.json', machine)
    manifest = json.loads((bundle / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    manifest['validation'] = {'status': 'PASS' if machine['LOCAL_VALIDATION_PASS'] else 'WINDOWS_PASS_LOCAL_PENDING_OR_FAILED', 'local': local_label, 'windows_ci': 'WINDOWS_CI_PASS', 'bank': 'BANK_FIELD_VALIDATION_REQUIRED', 'proof': proof}
    manifest['source_identity_scope'] = 'Exact Git archive before generated validation overlays; FILE_SHA256.json verifies final delivered bytes'
    manifest['recovery_change_validation'] = local_label + ' + WINDOWS_CI_PASS'
    manifest['work_item'] = 'REC3_FINAL_TURNKEY_PRODUCT_CONVERGENCE_CONTRACT_REISSUE'
    manifest['closure'] = machine['closure']
    manifest['closure_gates'] = gates
    write(bundle / 'PACKAGE_MANIFEST.json', manifest)
    provenance = json.loads((bundle / 'BUILD_PROVENANCE.json').read_text(encoding='utf-8'))
    provenance['windows_qualification'] = proof
    provenance['generated_delivery_overlays'] = ['MACHINE_VALIDATION_RESULT.json', 'PACKAGE_MANIFEST.json', 'BUILD_PROVENANCE.json', 'FILE_SHA256.json', 'windows-validation.json', 'windows-doctor.txt', 'windows-self-check.txt', 'windows-install.txt', 'windows-install-manifest.json']
    allowed_extra = set(provenance['generated_delivery_overlays'])
    files = sorted(p for p in bundle.rglob('*') if p.is_file() and (p.relative_to(bundle).as_posix() in original_checksums or p.relative_to(bundle).as_posix() in allowed_extra))
    provenance['files'] = [{'path': p.relative_to(bundle).as_posix(), 'size_bytes': p.stat().st_size, 'sha256': sha(p)} for p in files if p.name not in {'BUILD_PROVENANCE.json', 'FILE_SHA256.json'}]
    write(bundle / 'BUILD_PROVENANCE.json', provenance)
    checksums = {p.relative_to(bundle).as_posix(): sha(p) for p in files if p.name != 'FILE_SHA256.json'}
    write(bundle / 'FILE_SHA256.json', checksums)
    final = output / (bundle.name + '.zip')
    pending_zip = output / (final.name + '.partial')
    with zipfile.ZipFile(pending_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for p in files: archive.write(p, bundle.name + '/' + p.relative_to(bundle).as_posix())
    digest = sha(pending_zip)
    os.replace(pending_zip, final)
    (output / (final.name + '.sha256')).write_text(f'{digest}  {final.name}\n', encoding='ascii')
    for name in ('INSTALL_MANIFEST.json', 'windows-install-manifest.json', 'MACHINE_VALIDATION_RESULT.json', 'BUILD_PROVENANCE.json', 'PACKAGE_MANIFEST.json', 'VALIDATION_README.md', 'CAPABILITY_PARITY_MATRIX.md', 'OFFLINE_PAYLOAD_REGISTRY.json'):
        import shutil
        shutil.copy2(bundle / name, output / name)
    write(output / 'BUILD_RESULT.json', {'zip': final.name, 'sha256': digest, 'size_bytes': final.stat().st_size, 'source_head': provenance['source_head'], 'windows_ci': proof})
    print(json.dumps({'zip': str(final), 'sha256': digest, 'source_head': provenance['source_head']}))


if __name__ == '__main__': main()
