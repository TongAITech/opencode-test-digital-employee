#!/usr/bin/env python3
"""Build an offline Windows validation ZIP from an exact source commit + staged bytes.

This build never downloads or installs dependencies. Acquisition decisions belong
in OFFLINE_PAYLOAD_REGISTRY.json and are completed on the construction host.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def build(repo: Path, stage: Path, output: Path, version: str, allow_dirty: bool = False) -> dict:
    head = run_git(repo, 'rev-parse', 'HEAD')
    dirty = run_git(repo, 'status', '--porcelain')
    if dirty and not allow_dirty:
        raise RuntimeError('Commit source changes before building an exact-HEAD package.')
    registry = repo / 'OFFLINE_PAYLOAD_REGISTRY.json'
    if not registry.is_file():
        raise RuntimeError('OFFLINE_PAYLOAD_REGISTRY.json must exist before packaging.')
    inputs = json.loads(registry.read_text(encoding='utf-8'))
    runtime = stage / 'workspace-template' / 'runtime'
    required = ['python/python.exe', 'python/python312.dll', 'opencode/opencode.exe',
                'browser/chrome-win64/chrome.exe',
                'code-intelligence/codegraph/codegraph-server-win32-x64.exe',
                'code-intelligence/codegraph/onnxruntime.dll']
    missing = [name for name in required if not (runtime / name).is_file()]
    if missing:
        raise RuntimeError('Required offline files missing: ' + ', '.join(missing))
    name = f'AITest-V{version}-Recovery-Turnkey-Windows-x64'
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / name
    if bundle.exists():
        raise RuntimeError(f'Output already exists; use a fresh output directory: {bundle}')
    bundle.mkdir()
    archive = subprocess.check_output(['git', '-C', str(repo), 'archive', '--format=tar', head])
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
        for member in source.getmembers():
            destination = (bundle / member.name).resolve()
            if not destination.is_relative_to(bundle.resolve()) or member.issym() or member.islnk():
                raise RuntimeError('Unsafe source archive member: ' + member.name)
        source.extractall(bundle)
    if allow_dirty:
        # Explicit diagnostic mode only; cannot claim exact source HEAD.
        for name_in_repo in run_git(repo, 'ls-files').splitlines():
            path = repo / name_in_repo
            if path.is_file():
                destination = bundle / name_in_repo
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    shutil.copytree(stage, bundle, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.git'))
    shutil.copy2(registry, bundle / registry.name)
    expected = {}
    for artifact in inputs.get('staged_artifacts', []):
        entries = artifact.get('tree_manifest') or []
        if artifact.get('hash_kind') == 'file' and artifact.get('relative_target'):
            entries = [{'path': artifact['relative_target'], 'sha256': artifact['sha256']}]
        for entry in entries:
            path = bundle / entry['path']
            if not path.is_file() or sha256(path) != entry['sha256']:
                raise RuntimeError('Staged payload integrity mismatch: ' + entry['path'])
            expected[entry['path']] = entry['sha256']
    (bundle / 'PAYLOAD_SHA256SUMS.json').write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for required_entry in ['AITEST.sh', 'tools/recovery/launcher.py',
                           'tools/recovery/validate_package.py', 'VALIDATION_README.md',
                           'CAPABILITY_PARITY_MATRIX.md', 'MACHINE_VALIDATION_RESULT.json']:
        if not (bundle / required_entry).is_file():
            raise RuntimeError('Missing delivery entry: ' + required_entry)
    files = []
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            files.append({'path': path.relative_to(bundle).as_posix(),
                          'size_bytes': path.stat().st_size, 'sha256': sha256(path)})
    provenance = {
        'schema_version': 'aitest.build-provenance.v1', 'product_version': version,
        'package': name, 'built_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'repository': 'TongAITech/opencode-test-digital-employee',
        'source_head': head, 'source_branch': run_git(repo, 'branch', '--show-current'),
        'source_truth': 'DIRTY_DIAGNOSTIC_SNAPSHOT' if dirty else 'EXACT_GIT_HEAD',
        'architecture_baseline': 'v7/FROZEN/UNCHANGED',
        'runtime_truth': 'R1_EVENT_STREAM', 'G6': 'HOLD',
        'build_policy': 'LOCAL-FIRST / ONLINE-FALLBACK; build performs no downloads',
        'bank_host_online_install': False, 'registry_sha256': sha256(bundle / registry.name),
        'artifacts': inputs.get('staged_artifacts', []),
        'online_acquisitions': [a for a in inputs.get('artifacts', [])
                                if a.get('provenance', {}).get('type') == 'ONLINE_DOWNLOAD_AFTER_LOCAL_EXHAUSTION'],
        'files': files,
        'file_inventory_excludes': ['BUILD_PROVENANCE.json (avoids self-reference)'],
        'field_validation': 'BANK_FIELD_VALIDATION_REQUIRED',
    }
    (bundle / 'BUILD_PROVENANCE.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    file_checksums = {path.relative_to(bundle).as_posix(): sha256(path)
                      for path in sorted(bundle.rglob('*')) if path.is_file()
                      and path.name != 'FILE_SHA256.json'
                      and not path.relative_to(bundle).parts[0] == 'data'}
    (bundle / 'FILE_SHA256.json').write_text(
        json.dumps(file_checksums, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    zip_path = output / (name + '.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as target:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                target.write(path, name + '/' + path.relative_to(bundle).as_posix())
    digest = sha256(zip_path)
    (output / (zip_path.name + '.sha256')).write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
    result = {'zip': str(zip_path.resolve()), 'sha256': digest,
              'size_bytes': zip_path.stat().st_size, 'source_head': head,
              'bundle': str(bundle.resolve()), 'payload_file_count': len(expected)}
    (output / 'BUILD_RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--payload-stage', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--version', default='1.9.5')
    parser.add_argument('--allow-dirty-diagnostic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.payload_stage.resolve(),
                           args.output_dir.resolve(), args.version, args.allow_dirty_diagnostic), indent=2))


if __name__ == '__main__':
    main()
