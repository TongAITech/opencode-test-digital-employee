"""Package-owned assembly from approved local capability configuration.

No operator-written Mission factory is required. Configuration identifies tools,
inputs and the existing host environment adapter; it supplies no gate results.
DSH provider/profile provisioning is a separate required integration.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_code_tool_binding import NATIVE_CODE_TOOLS
from rc7_runtime.rc72_bank_pip_mirror import NativeBankPipMirrorService
from rc7_runtime.rc72_ledger_lock import ledger_lock
from rc7_runtime.rc72_mission_factory import ROLES, MissionWorkerBinding, MissionHostBindings
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource
from rc7_runtime.rc72_worker_http_auth import validate_asset_root
from .execution_environment import ExecutionEnvironmentLoader, ExecutionEnvironmentLoadError
from .rc72_tool_environment import package_tool_environment, OWNED_NAMES

SCHEMA = 'RC72_MISSION_CAPABILITIES_V1'
_FIELDS = {'schema', 'release_id', 'source_commit', 'package_root', 'state_root',
           'dsh_bin', 'patch_path', 'inputs', 'role_tools', 'tool_registry',
           'environment_module', 'archive', 'pip_field_config', 'model_environment_names'}
_OPTIONAL_FIELDS = {'http_auth_asset_root'}
_FORBIDDEN_ENV = {'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'DSH_HOME',
                  'XDG_CONFIG_HOME', 'PYTHONPATH', 'PYTHONHOME', 'NODE_OPTIONS'}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ContractError('MISSION_CONFIG_DUPLICATE_KEY')
        result[key] = value
    return result


def _tools(value):
    return (isinstance(value, list) and bool(value)
        and all(isinstance(t, str) and t.strip() == t and t and '*' not in t for t in value)
        and len(set(value)) == len(value))


def _controller_key(truth, directory):
    """Cold-stable owned authority, never a Worker environment value."""
    with ledger_lock(truth, busy='MISSION_CONFIG_CONTROLLER_BUSY'):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/'controller.key'
        if path.is_symlink():
            raise ContractError('MISSION_CONFIG_CONTROLLER_KEY_SYMLINK_FORBIDDEN')
        if path.exists():
            raw = path.read_bytes()
            if len(raw) != 32:
                raise ContractError('MISSION_CONFIG_CONTROLLER_KEY_INVALID')
            return raw
        raw = secrets.token_bytes(32)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return raw


def configured_mission_bindings(truth, *, release_id, source_commit, config_path):
    path = Path(config_path).expanduser().resolve()
    try:
        config = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs)
    except ContractError:
        raise
    except (OSError, ValueError):
        raise ContractError('MISSION_CONFIG_READ_FAILED') from None
    if (not isinstance(config, dict) or not _FIELDS <= set(config) or bool(set(config) - _FIELDS - _OPTIONAL_FIELDS) or config.get('schema') != SCHEMA):
        raise ContractError('MISSION_CONFIG_EXACT_CAPABILITY_FIELDS_REQUIRED')
    if (not isinstance(release_id,str) or not release_id.strip()
            or not isinstance(source_commit,str) or not re.fullmatch('[0-9a-f]{40}', source_commit) or config['source_commit'] != source_commit
            or config['release_id'] != release_id):
        raise ContractError('MISSION_CONFIG_RELEASE_SOURCE_MISMATCH')

    def configured_path(name, *, file=False):
        value = config[name]
        if not isinstance(value, str) or not value.strip():
            raise ContractError('MISSION_CONFIG_PATH_REQUIRED')
        result = Path(value).expanduser()
        result = (path.parent/result).resolve() if not result.is_absolute() else result.resolve()
        if file and not result.is_file():
            raise ContractError('MISSION_CONFIG_BOUND_FILE_REQUIRED')
        return result

    root = configured_path('package_root')
    if not (root/'SOURCE_COMMIT').is_file() or (root/'SOURCE_COMMIT').read_text().strip() != source_commit:
        raise ContractError('MISSION_CONFIG_EXACT_PACKAGE_SOURCE_REQUIRED')
    state = configured_path('state_root')
    auth_root = None
    if 'http_auth_asset_root' in config:
        auth_root = validate_asset_root(configured_path('http_auth_asset_root'),
            forbidden_roots=[root, state])
    dsh = configured_path('dsh_bin', file=True)
    patch = configured_path('patch_path', file=True)
    archive = configured_path('archive', file=True)
    field = configured_path('pip_field_config', file=True)
    role_tools, registry = config['role_tools'], config['tool_registry']
    if (not isinstance(role_tools, dict) or set(role_tools) != set(ROLES)
            or any(not _tools(v) for v in role_tools.values())
            or any(set(role_tools[r]) != set(NATIVE_CODE_TOOLS) for r in ('code','code_review'))):
        raise ContractError('MISSION_CONFIG_EXACT_ROLE_TOOLS_REQUIRED')
    if (not isinstance(registry, dict) or not registry
            or any(not isinstance(k, str) or not k.strip() or not _tools(v) for k,v in registry.items())):
        raise ContractError('MISSION_CONFIG_EXACT_EXECUTION_TOOLS_REQUIRED')
    inputs = config['inputs']
    if not isinstance(inputs, list) or not inputs:
        raise ContractError('MISSION_CONFIG_ORIGINAL_INPUTS_REQUIRED')
    resources = []
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {'source_ref','path'} or not isinstance(item['path'], str):
            raise ContractError('MISSION_CONFIG_EXACT_INPUT_FIELDS_REQUIRED')
        resource_path = Path(item['path']).expanduser()
        if not resource_path.is_absolute():
            resource_path = path.parent/resource_path
        resources.append(N1ReadResource(item['source_ref'], resource_path))
    if len({r.source_ref for r in resources}) != len(resources):
        raise ContractError('MISSION_CONFIG_DUPLICATE_ORIGINAL_INPUT')
    names = config['model_environment_names']
    if not isinstance(names, list) or any(not isinstance(n,str) for n in names) or len(set(names)) != len(names):
        raise ContractError('MISSION_CONFIG_EXPLICIT_MODEL_ENVIRONMENT_REQUIRED')
    environment = {}
    for name in names:
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name.upper() in _FORBIDDEN_ENV or name.upper() in OWNED_NAMES
                or any(t in name.upper() for t in ('CAPTAIN','COORDINATOR','SIGNING_KEY','AUTHORITY_KEY','HMAC_KEY'))):
            raise ContractError('MISSION_CONFIG_CONTROL_ENVIRONMENT_FORBIDDEN')
        if not os.environ.get(name):
            raise ContractError('MISSION_CONFIG_SELECTED_MODEL_ENVIRONMENT_MISSING')
        environment[name] = os.environ[name]
    tools_environment = package_tool_environment(root)
    environment.update(tools_environment)
    try:
        adapter = ExecutionEnvironmentLoader.load(config['environment_module']).adapter
    except ExecutionEnvironmentLoadError:
        raise ContractError('MISSION_CONFIG_EXECUTION_ENVIRONMENT_UNAVAILABLE') from None
    if not callable(getattr(adapter, 'cleanup', None)):
        raise ContractError('MISSION_CONFIG_EXECUTION_CLEANUP_REQUIRED')
    scope = hashlib.sha256(json.dumps([release_id,source_commit,os.path.normcase(str(Path(truth.store.path).resolve()))],
        separators=(',',':')).encode()).hexdigest()
    owned = state/scope
    key = _controller_key(truth, owned/'authority')

    def authority(role):
        return RC72AuthorityRuntime(hmac.new(key, role.encode(), hashlib.sha256).digest())

    workers = {}
    for role in ROLES:
        arguments = dict(dsh_bin=str(dsh), patch_path=str(patch), cwd=str(root), truth=truth,
            authority=authority('worker:'+role), coordinator_instance_id='rc72-controller-'+scope[:24],
            release_id=release_id, state_root=str(owned/'workers'/role), env=environment)
        launcher = (NativeN1ReadDshLauncher(resources=resources, **arguments) if role == 'reality'
                    else DshHeadlessWorkerLauncher(**arguments))
        workers[role] = MissionWorkerBinding(launcher, tuple(role_tools[role]))
    execution = authority('execution')
    mirror = NativeBankPipMirrorService(truth, release_id=release_id, source_commit=source_commit,
        authority=authority('bank-pip-mirror'), package_root=root, archive=archive,
        field_config=field, evidence_root=owned/'pip-mirror')
    return MissionHostBindings(workers, mirror, execution, adapter, registry, tools_environment or None, auth_root)


def create_mission_bindings(*, truth, release_id, source_commit):
    """Fixed host-module entry. Configuration location contains no secret value."""
    location = os.environ.get('PFC_RC72_MISSION_CONFIG')
    if not location:
        raise ContractError('MISSION_CONFIG_LOCATION_REQUIRED')
    return configured_mission_bindings(truth, release_id=release_id,
        source_commit=source_commit, config_path=location)
