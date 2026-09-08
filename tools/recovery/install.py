"""Materialize sealed Windows dependencies; never launch OpenCode or download.

The transport manifest stays authoritative for immutable delivered files. Only
INSTALL_MANIFEST.json becomes an installation-specific overlay, bound to its
original digest, the sealed checksum inventory, and the final installation path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import uuid


SCHEMA = 'aitest.install-manifest.v2'
DEFAULT_TARGET = str(Path.cwd() / 'AITest-Workspace')
PYTHON_RELATIVE = 'runtime/python/python.exe'
SOURCE_PYTHON_RELATIVE = 'workspace-template/' + PYTHON_RELATIVE
REQUIRED_FILES = (
    'INSTALL.sh', 'AITEST.sh', 'tools/recovery/install.py', 'tools/recovery/launcher.py',
    'tools/recovery/host_opencode.py',
    'FILE_SHA256.json', 'PAYLOAD_SHA256SUMS.json', 'BUILD_PROVENANCE.json',
    'OFFLINE_PAYLOAD_REGISTRY.json', 'INSTALL_MANIFEST.json', 'runtime-lock.json',
    'PACKAGE_MANIFEST.json', 'MACHINE_VALIDATION_RESULT.json',
    'CAPABILITY_PARITY_MATRIX.md', 'VALIDATION_README.md',
    'workspace-template/opencode.json', 'workspace-template/AGENTS.md',
    'workspace-template/.opencode/agents/aitest-director.md',
    'workspace-template/ai-test/runtime/aitest_runtime/canonical_runtime.py',
    SOURCE_PYTHON_RELATIVE, 'workspace-template/runtime/python/python312.dll',
    'workspace-template/runtime/opencode/opencode.exe',
    'workspace-template/runtime/browser/chrome-win64/chrome.exe',
    'workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe',
    'workspace-template/runtime/code-intelligence/codegraph/onnxruntime.dll',
    'workspace-template/runtime/tools/rg/rg.exe', 'workspace-template/runtime/tools/k6/k6.exe',
    'workspace-template/runtime/tools/java/bin/java.exe',
)
DATA_DIRECTORIES = ('state', 'logs', 'evidence', 'imports', 'exports')


def installation_mapping(checksums: dict) -> dict[str, str]:
    """Materialize only runtime assets; construction source remains transport-only."""
    mapping = {}
    metadata = {'AITEST.sh', 'INSTALL_MANIFEST.json', 'runtime-lock.json',
                'BUILD_PROVENANCE.json', 'OFFLINE_PAYLOAD_REGISTRY.json',
                'PAYLOAD_SHA256SUMS.json', 'PACKAGE_MANIFEST.json',
                'MACHINE_VALIDATION_RESULT.json', 'VALIDATION_README.md'}
    runtime_tools = {'tools/recovery/install.py', 'tools/recovery/launcher.py',
                     'tools/recovery/host_opencode.py'}
    for source in checksums:
        if source in metadata or source in runtime_tools:
            mapping[source] = source
        elif source.startswith('workspace-template/'):
            target = source.removeprefix('workspace-template/')
            if target.startswith('runtime/opencode/'):
                continue  # Construction carrier only; bank uses host OpenCode.
            if target in {'AGENTS.md', 'opencode.json', 'VERSION', '.gitignore'} or target.startswith(
                    ('.opencode/', 'ai-test/', 'runtime/', 'tools/', 'bindings/')):
                mapping[source] = target
    values = [value.casefold() for value in mapping.values()]
    if len(values) != len(set(values)):
        raise InstallError('INSTALL_TARGET_MAPPING_COLLISION')
    return mapping


class InstallError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise InstallError('INVALID_JSON: ' + path.name) from exc
    if not isinstance(value, dict):
        raise InstallError('JSON_OBJECT_REQUIRED: ' + path.name)
    return value


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def safe_path(root: Path, relative: str) -> Path:
    """Windows-safe inventory members, with no path or link escape."""
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise InstallError('UNSAFE_INVENTORY_PATH')
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or any(p in ('..', '.') for p in parts):
        raise InstallError('UNSAFE_INVENTORY_PATH')
    if PurePosixPath(relative).as_posix() != relative:
        raise InstallError('NON_CANONICAL_INVENTORY_PATH')
    path = root
    for part in parts:
        if part.rstrip(' .') != part or part.split('.')[0].upper() in {
            'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
            *(f'LPT{i}' for i in range(1, 10)),
        }:
            raise InstallError('UNSAFE_WINDOWS_INVENTORY_PATH')
        path /= part
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise InstallError('INVENTORY_LINK_FORBIDDEN: ' + relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise InstallError('INVENTORY_PATH_ESCAPE')
    return path


def checksum_inventory(root: Path) -> dict:
    checksums = read_json(root / 'FILE_SHA256.json')
    if not checksums:
        raise InstallError('EMPTY_CHECKSUM_INVENTORY')
    seen = set()
    for relative, expected in checksums.items():
        safe_path(root, relative)
        if relative == 'FILE_SHA256.json' or relative.casefold() in seen:
            raise InstallError('INVALID_CHECKSUM_INVENTORY')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise InstallError('INVALID_SHA256: ' + relative)
        seen.add(relative.casefold())
    missing = [name for name in REQUIRED_FILES if name != 'FILE_SHA256.json' and name not in checksums]
    if missing:
        raise InstallError('REQUIRED_PAYLOAD_NOT_SEALED: ' + ', '.join(missing))
    return checksums


def verify_install_identity(root: Path) -> list[str]:
    """Return actionable failures; does not create state or launch any process."""
    root = Path(root).resolve()
    try:
        manifest = read_json(root / 'INSTALL_MANIFEST.json')
        checksums = read_json(root / 'FILE_SHA256.json')
        provenance = read_json(root / 'BUILD_PROVENANCE.json')
        failures = []
        if manifest.get('schema_version') != SCHEMA or manifest.get('status') != 'INSTALLED':
            failures.append('INSTALL_REQUIRED: run ./INSTALL.sh from the extracted package')
        if (root / '.AITEST_INSTALLING').exists():
            failures.append('INSTALL_INCOMPLETE')
        for key, expected in (
            ('install_root', str(root)), ('workspace_root', str(root)),
            ('durable_root', str(root / 'data')), ('portable_python', str(root / PYTHON_RELATIVE)),
        ):
            value = manifest.get(key)
            if not isinstance(value, str) or Path(value).resolve() != Path(expected).resolve():
                failures.append('INSTALL_LOCATION_MISMATCH: ' + key)
        if manifest.get('source_file_sha256_sha256') != sha256(root / 'FILE_SHA256.json'):
            failures.append('INSTALL_SOURCE_CHECKSUM_IDENTITY_MISMATCH')
        if manifest.get('file_map') != installation_mapping(checksums):
            failures.append('INSTALL_MATERIALIZATION_MAPPING_MISMATCH')
        if (root / 'workspace-template').exists() or (root / 'runtime/opencode').exists():
            failures.append('INSTALLED_WORKSPACE_TOPOLOGY_INVALID')
        if manifest.get('opencode_policy') != 'HOST_NATIVE_OPENCODE':
            failures.append('HOST_NATIVE_OPENCODE_REQUIRED')
        if not checksums.get('INSTALL_MANIFEST.json') or manifest.get('source_install_manifest_sha256') != checksums.get('INSTALL_MANIFEST.json'):
            failures.append('INSTALL_SOURCE_MANIFEST_IDENTITY_MISMATCH')
        if manifest.get('source_head') != provenance.get('source_head') or not provenance.get('source_head'):
            failures.append('INSTALL_SOURCE_HEAD_MISMATCH')
        try:
            uuid.UUID(str(manifest.get('install_id')))
        except (ValueError, TypeError, AttributeError):
            failures.append('INSTALL_ID_MISSING_OR_INVALID')
        report = manifest.get('self_check')
        if not isinstance(report, dict) or report.get('status') != 'PASS':
            failures.append('INSTALL_SELF_CHECK_NOT_PASS')
        if manifest.get('processes_started') != [] or manifest.get('network_install_performed') is not False:
            failures.append('INSTALL_LIFECYCLE_CONTRACT_INVALID')
        return failures
    except (InstallError, OSError, TypeError, ValueError) as exc:
        return ['INSTALL_IDENTITY_INVALID: ' + type(exc).__name__]


def verify_package(root: Path, installed: bool = False) -> dict:
    """Verify every delivered byte and cross-check all offline registry entries."""
    root = Path(root).resolve()
    checksums = checksum_inventory(root)
    if installed:
        failures = verify_install_identity(root)
        if failures:
            raise InstallError('; '.join(failures))
    mapping = installation_mapping(checksums) if installed else {p: p for p in checksums}
    for relative, expected in checksums.items():
        if installed and relative == 'INSTALL_MANIFEST.json':
            continue
        if relative not in mapping:
            continue
        path = safe_path(root, mapping[relative])
        if not path.is_file() or sha256(path) != expected:
            raise InstallError('PACKAGE_SHA256_MISMATCH: ' + relative)
    registry = read_json(root / 'OFFLINE_PAYLOAD_REGISTRY.json')
    payload_checksums = read_json(root / 'PAYLOAD_SHA256SUMS.json')
    expected_payload = {}
    for artifact in registry.get('staged_artifacts', []):
        entries = artifact.get('tree_manifest') or []
        if artifact.get('hash_kind') == 'file' and artifact.get('relative_target'):
            entries = [{'path': artifact['relative_target'], 'sha256': artifact['sha256']}]
        for entry in entries:
            relative, expected = entry['path'], entry['sha256']
            safe_path(root, relative)
            if relative in expected_payload and expected_payload[relative] != expected:
                raise InstallError('CONFLICTING_OFFLINE_PAYLOAD_IDENTITY: ' + relative)
            expected_payload[relative] = expected
    if not expected_payload or expected_payload != payload_checksums:
        raise InstallError('OFFLINE_REGISTRY_INVENTORY_MISMATCH')
    for relative, expected in expected_payload.items():
        if checksums.get(relative) != expected:
            raise InstallError('OFFLINE_PAYLOAD_NOT_SEALED: ' + relative)
    lock = read_json(root / 'runtime-lock.json')
    for payload in lock.get('payloads', {}).values():
        for item in [payload, *payload.get('companions', [])]:
            if item.get('relative_target') and item.get('sha256'):
                if checksums.get(item['relative_target']) != item['sha256']:
                    raise InstallError('RUNTIME_LOCK_MISMATCH: ' + item['relative_target'])
    if not any(name.startswith('workspace-template/runtime/tools/zap/zap-') and name.endswith('.jar') for name in checksums):
        raise InstallError('ZAP_PAYLOAD_MISSING')
    provenance = read_json(root / 'BUILD_PROVENANCE.json')
    if provenance.get('registry_sha256') != sha256(root / 'OFFLINE_PAYLOAD_REGISTRY.json'):
        raise InstallError('BUILD_REGISTRY_IDENTITY_MISMATCH')
    if not installed and read_json(root / 'INSTALL_MANIFEST.json').get('status') != 'NOT_INSTALLED':
        raise InstallError('FRESH_TRANSPORT_PACKAGE_REQUIRED')
    return {'status': 'PASS', 'file_count': len(checksums), 'payload_file_count': len(expected_payload),
            'source_head': provenance.get('source_head'), 'checksums': checksums}


def self_check(root: Path) -> dict:
    """Executed only by the installed portable Python, without launching tools."""
    root = root.resolve()
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise InstallError('WINDOWS_X64_REQUIRED')
    if Path(sys.executable).resolve() != root / PYTHON_RELATIVE:
        raise InstallError('INSTALLED_PORTABLE_PYTHON_REQUIRED')
    lock = read_json(root / 'runtime-lock.json')
    expected_version = lock['payloads']['python']['version']
    if platform.python_version() != expected_version:
        raise InstallError('PORTABLE_PYTHON_VERSION_MISMATCH')
    modules = {}
    for name, distribution in (('httpx', 'httpx'), ('pytest', 'pytest'), ('playwright.sync_api', 'playwright'),
                               ('greenlet', 'greenlet'), ('pypdf', 'pypdf')):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(root / 'runtime/python'):
            raise InstallError('HOST_PYTHON_MODULE_FORBIDDEN: ' + name)
        actual = importlib.metadata.version(distribution)
        expected = lock.get('payloads', {}).get(distribution, {}).get('version')
        if expected and expected != actual:
            raise InstallError('PORTABLE_MODULE_VERSION_MISMATCH: ' + name)
        modules[distribution] = actual
    workspace = root
    sys.path.insert(0, str(workspace / 'ai-test/runtime'))
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    db = root / 'data/state/runtime-spine.db'
    runtime = create_canonical_runtime(workspace, db_path=db)
    if Path(runtime.db_path).resolve() != db:
        raise InstallError('R1_EVENT_STREAM_LOCATION_MISMATCH')
    if (workspace / 'ai-test/state/aitest.db').exists():
        raise InstallError('LEGACY_PRODUCT_TRUTH_FORBIDDEN')
    return {'status': 'PASS', 'python': platform.python_version(), 'executable': str(Path(sys.executable).resolve()),
            'modules': modules, 'runtime_truth': 'R1_EVENT_STREAM', 'runtime_db': str(db),
            'opencode_process_started': False, 'control_loop_started': False,
            'model_auth_required': False, 'bank_auth_required': False, 'online_install': False}


def run_installed_self_check(target: Path) -> dict:
    # Deliberately do not forward provider keys, tokens, PYTHONPATH or host XDG settings.
    inherited = {'systemroot', 'windir', 'comspec', 'temp', 'tmp', 'pathext', 'systemdrive'}
    env = {key: value for key, value in os.environ.items() if key.lower() in inherited}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               PYTHONIOENCODING='utf-8', PIP_NO_INDEX='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
               AITEST_WORKSPACE_ROOT=str(target), PFC_LOCAL_STATE_ROOT=str(target / 'data'),
               AITEST_RUNTIME_SPINE_DB=str(target / 'data/state/runtime-spine.db'))
    result = subprocess.run([str(target / PYTHON_RELATIVE), '-I', '-B', '-X', 'utf8',
                             str(target / 'tools/recovery/install.py'), '--self-check', str(target)],
                            cwd=target, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
    if result.returncode != 0:
        # Only error classes/codes from our child are reported; environment values are never printed.
        raise InstallError('INSTALLED_SELF_CHECK_FAILED: ' + result.stdout.strip()[-2000:])
    report = json.loads(result.stdout)
    if report.get('status') != 'PASS':
        raise InstallError('INSTALLED_SELF_CHECK_NOT_PASS')
    return report


def install(source: Path, target: Path) -> dict:
    source = source.resolve()
    # Check lexical existence before resolve so dangling links are refused too.
    if os.path.lexists(target):
        raise InstallError('INSTALL_TARGET_EXISTS: existing Runtime/Data were not modified; use a new empty location')
    target = target.resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise InstallError('INSTALL_TARGET_OVERLAPS_TRANSPORT')
    integrity = verify_package(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()  # Atomic claim: never copy into a pre-existing destination.
    except FileExistsError as exc:
        raise InstallError('INSTALL_TARGET_EXISTS: destination appeared during integrity verification') from exc
    marker = target / '.AITEST_INSTALLING'
    install_id = str(uuid.uuid4())
    write_json(marker, {'install_id': install_id, 'status': 'INSTALLING'})
    try:
        mapping = installation_mapping(integrity['checksums'])
        for relative, destination in {**mapping, 'FILE_SHA256.json': 'FILE_SHA256.json'}.items():
            src = safe_path(source, relative)
            dest = safe_path(target, destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        # Re-measure installed bytes; transport changes or copy failures cannot become READY.
        for relative, destination in mapping.items():
            if sha256(target / destination) != integrity['checksums'][relative]:
                raise InstallError('MATERIALIZED_FILE_SHA256_MISMATCH: ' + destination)
        for directory in DATA_DIRECTORIES:
            (target / 'data' / directory).mkdir(parents=True, exist_ok=True)
        bindings = target / 'bindings'
        bindings.mkdir(parents=True, exist_ok=True)
        binding_status = bindings / 'installation.json'
        if binding_status.exists():
            raise InstallError('UNEXPECTED_INITIAL_BINDING')
        write_json(binding_status, {'schema_version': 'aitest.install-bindings.v1', 'install_id': install_id,
                   'status': 'BANK_BINDING_REQUIRED', 'approved': False,
                   'capabilities': {name: 'BANK_BINDING_REQUIRED' for name in ('Starlink', '4A', 'CAT', 'DB', 'Execution')},
                   'model': 'AUTH_REQUIRED', 'credentials_copied': False})
        report = run_installed_self_check(target)
        write_json(target / 'data/logs/install-self-check.json', report)
        identity = {'schema_version': SCHEMA, 'status': 'INSTALLED', 'install_id': install_id,
                    'installed_at_utc': datetime.now(timezone.utc).isoformat(),
                    'install_root': str(target), 'workspace_root': str(target),
                    'durable_root': str(target / 'data'), 'portable_python': str(target / PYTHON_RELATIVE),
                    'source_head': integrity['source_head'],
                    'source_file_sha256_sha256': sha256(target / 'FILE_SHA256.json'),
                    'source_install_manifest_sha256': integrity['checksums']['INSTALL_MANIFEST.json'],
                    'copied_file_count': len(mapping), 'offline_payload_file_count': sum(p.startswith('workspace-template/runtime/') and p in mapping for p in integrity['checksums']),
                    'file_map': mapping, 'opencode_policy': 'HOST_NATIVE_OPENCODE',
                    'host_opencode_exact_version_pin': None, 'transport_is_runtime_location': False,
                    'architecture_baseline': 'v7/FROZEN/UNCHANGED', 'runtime_truth': 'R1_EVENT_STREAM',
                    'self_check': report, 'processes_started': [], 'network_install_performed': False,
                    'host_credentials_read_or_copied': False, 'daily_entry': str(target / 'AITEST.sh'),
                    'field_validation': 'BANK_FIELD_VALIDATION_REQUIRED'}
        write_json(target / 'INSTALL_MANIFEST.json', identity)
        marker.unlink()
        failures = verify_install_identity(target)
        if failures:
            raise InstallError('; '.join(failures))
        return identity
    except BaseException as exc:
        write_json(marker, {'install_id': install_id, 'status': 'FAILED', 'error_class': type(exc).__name__,
                           'recovery': 'Installation is incomplete and cannot be started. Preserve this directory for inspection; install to a new location.'})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--target', type=Path, default=Path(DEFAULT_TARGET))
    parser.add_argument('--git-bash', action='store_true')
    parser.add_argument('--self-check', type=Path)
    args = parser.parse_args()
    try:
        if args.self_check:
            print(json.dumps(self_check(args.self_check), ensure_ascii=False))
            return 0
        if os.name != 'nt' or not args.git_bash or not os.environ.get('MSYSTEM', '').startswith(('MINGW', 'MSYS')):
            raise InstallError('WINDOWS_GIT_BASH_REQUIRED: run ./INSTALL.sh in Git Bash')
        if Path(sys.executable).resolve() != args.source.resolve() / SOURCE_PYTHON_RELATIVE:
            raise InstallError('PACKAGE_PORTABLE_PYTHON_REQUIRED')
        result = install(args.source, args.target)
        print('INSTALL_START_LIFECYCLE=PASS')
        print('安装完成；OpenCode 尚未启动。正式 Runtime：' + result['install_root'])
        print('以后请在安装目录运行 ./AITEST.sh。模型与行内授权在启动后的引导中完成。')
        return 0
    except (InstallError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
