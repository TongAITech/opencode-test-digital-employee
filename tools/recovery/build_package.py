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
import os
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


SOURCE_IDENTITY_FORMULA = "sha256(UTF-8 sorted `<file_sha256>  <path>` lines, exactly one final newline; tracked files from `git ls-files`; excludes PACKAGE_MANIFEST.json)"


def archive_source_identity(bundle: Path, source_paths: list[str]) -> dict:
    """Measure committed archive bytes before any derived payload is copied."""
    files = [{'path': relative, 'size_bytes': (bundle / relative).stat().st_size,
              'sha256': sha256(bundle / relative)}
             for relative in sorted(source_paths) if relative != 'PACKAGE_MANIFEST.json']
    canonical = ('\n'.join(f"{entry['sha256']}  {entry['path']}" for entry in files) + '\n').encode('utf-8')
    return {'formula': SOURCE_IDENTITY_FORMULA, 'file_count': len(files),
            'source_content_identity': hashlib.sha256(canonical).hexdigest(),
            'scope': 'Exact Git archive before derived payload or generated delivery overlays',
            'excluded_paths': ['PACKAGE_MANIFEST.json'], 'files': files}


def seal_package_source(bundle: Path, head: str, identity: dict, dirty: bool) -> dict:
    """Finalize generated source metadata without changing committed source bytes."""
    path = bundle / 'PACKAGE_MANIFEST.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    before = sha256(path)
    if manifest.get('source_identity_formula') not in (None, SOURCE_IDENTITY_FORMULA):
        raise RuntimeError('Unsupported declared source identity formula')
    scope = 'Exact Git archive before derived payload and generated delivery overlays; FILE_SHA256.json verifies final delivered bytes'
    if dirty:
        scope += '; diagnostic working-tree changes are excluded from this committed-source identity'
    manifest.update(source_identity_formula=SOURCE_IDENTITY_FORMULA,
                    source_content_identity=identity['source_content_identity'],
                    candidate_commit=head, source_identity_scope=scope,
                    candidate_commit_semantics='Exact Git commit archived for this build; generated manifest and payload overlays are recorded in BUILD_PROVENANCE.json')
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'path': 'PACKAGE_MANIFEST.json', 'scope': 'BUILD_TIME_SOURCE_IDENTITY_SEAL',
            'previous_sha256': before, 'generated_sha256': sha256(path),
            'updated_fields': ['source_identity_formula', 'source_content_identity',
                               'candidate_commit', 'source_identity_scope', 'candidate_commit_semantics']}


def build(repo: Path, stage: Path, output: Path, version: str, allow_dirty: bool = False, store_only: bool = False) -> dict:
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
    archive = subprocess.check_output(['git', '-C', str(repo), '-c', 'core.autocrlf=false',
                                       '-c', 'core.eol=lf', 'archive', '--format=tar', head])
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
        for member in source.getmembers():
            destination = (bundle / member.name).resolve()
            if not destination.is_relative_to(bundle.resolve()) or member.issym() or member.islnk():
                raise RuntimeError('Unsafe source archive member: ' + member.name)
        source_paths = [member.name for member in source.getmembers() if member.isfile()]
        source.extractall(bundle)
    source_identity = archive_source_identity(bundle, source_paths)
    archive_manifest_sha256 = sha256(bundle / 'PACKAGE_MANIFEST.json')
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
    # Keep the committed archive's registry bytes. A Windows checkout may use
    # CRLF while Git stores LF; copying the working-tree file would introduce
    # an undeclared source overlay despite an otherwise clean exact-HEAD build.
    generated_manifest_overlay = seal_package_source(bundle, head, source_identity, bool(dirty))
    generated_manifest_overlay['source_archive_sha256'] = archive_manifest_sha256
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
    for required_entry in ['INSTALL.sh', 'INSTALL_MANIFEST.json', 'AITEST.sh', 'tools/recovery/install.py', 'tools/recovery/launcher.py',
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
        'source_head': head, 'source_branch': run_git(repo, 'branch', '--show-current') or os.environ.get('GITHUB_REF_NAME', ''),
        'source_truth': 'DIRTY_DIAGNOSTIC_SNAPSHOT' if dirty else 'EXACT_GIT_HEAD',
        'source_content_identity': source_identity['source_content_identity'],
        'source_identity': source_identity,
        'generated_build_overlays': [generated_manifest_overlay],
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
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED if store_only else zipfile.ZIP_DEFLATED, compresslevel=None if store_only else 1) as target:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                target.write(path, name + '/' + path.relative_to(bundle).as_posix())
    digest = sha256(zip_path)
    (output / (zip_path.name + '.sha256')).write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
    result = {'zip': str(zip_path.resolve()), 'sha256': digest,
              'size_bytes': zip_path.stat().st_size, 'source_head': head,
              'source_content_identity': source_identity['source_content_identity'],
              'bundle': str(bundle.resolve()), 'payload_file_count': len(expected)}
    (output / 'BUILD_RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--payload-stage', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--version', default='1.12.0')
    parser.add_argument('--allow-dirty-diagnostic', action='store_true')
    parser.add_argument('--store-only', action='store_true', help='Fast construction-to-CI transport ZIP; Windows qualification compresses the deliverable')
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.payload_stage.resolve(),
                           args.output_dir.resolve(), args.version, args.allow_dirty_diagnostic, args.store_only), indent=2))


if __name__ == '__main__':
    main()
