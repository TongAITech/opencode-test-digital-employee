"""Explicit, secret-free host provider binding for the pinned OpenCode 1.18.3.

Discovery only stats known config paths. Approval permits bounded config inspection;
only the selected provider and local plugin/module references reach inline config.
Host auth stores are never opened and host config is never passed to OpenCode.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

MAX_CONFIG_BYTES = 1024 * 1024
SECRET_KEY = re.compile(r'(api.?key|access.?key|private.?key|password|passwd|token|secret|authorization|cookie|credential)', re.I)
ENV_REF = re.compile(r'^\{env:[A-Za-z_][A-Za-z0-9_]*\}$')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_.:@/-]{1,240}$')
BUNDLED_SDKS = {'@ai-sdk/openai-compatible', '@ai-sdk/openai', '@ai-sdk/anthropic', '@ai-sdk/google', '@ai-sdk/azure'}


class BindingRequired(ValueError):
    """Public messages are fixed codes: never include source config or secrets."""


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''): result.update(block)
    return result.hexdigest()


def discover(environ=None, home=None):
    """Existence and size only; no config/auth content read before approval."""
    env = os.environ if environ is None else environ
    root = Path(home or Path.home())
    xdg = Path(env.get('XDG_CONFIG_HOME') or root / '.config')
    paths = [xdg / 'opencode' / name for name in ('config.json', 'opencode.json', 'opencode.jsonc')]
    if env.get('OPENCODE_CONFIG'): paths.append(Path(env['OPENCODE_CONFIG']).expanduser())
    if env.get('OPENCODE_CONFIG_DIR'):
        paths.extend(Path(env['OPENCODE_CONFIG_DIR']).expanduser() / name for name in ('opencode.json', 'opencode.jsonc'))
    candidates = []
    seen = set()
    for path in paths:
        try:
            path = path.resolve()
            if path in seen or not path.is_file(): continue
            seen.add(path)
            candidates.append({'path': str(path), 'size_bytes': path.stat().st_size, 'content_inspected': False})
        except (OSError, RuntimeError):
            continue
    return {'status': 'DISCOVERED' if candidates else 'NOT_FOUND', 'candidates': candidates,
            'secret_access': 'NONE', 'host_auth_store_access': 'FORBIDDEN'}


def _jsonc(text):
    # Strip comments outside JSON strings, then trailing commas outside strings.
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda m: m.group(0) if m.group(0).startswith('"') else ' ', text)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
                  lambda m: m.group(0) if m.group(0).startswith('"') else '', text)
    try: value = json.loads(text)
    except (ValueError, TypeError): raise BindingRequired('HOST_CONFIG_JSONC_INVALID') from None
    if not isinstance(value, dict): raise BindingRequired('HOST_CONFIG_OBJECT_REQUIRED')
    return value


def _read_config(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
        raise BindingRequired('HOST_CONFIG_MISSING_OR_TOO_LARGE')
    try: return _jsonc(path.read_text(encoding='utf-8-sig'))
    except UnicodeError: raise BindingRequired('HOST_CONFIG_ENCODING_INVALID') from None


def _safe(value, key=''):
    if key.lower() == 'headers':
        if not isinstance(value, dict) or any(not isinstance(v, str) or not ENV_REF.fullmatch(v) for v in value.values()):
            raise BindingRequired('HEADER_VALUES_REQUIRE_ENV_REFERENCES')
    if SECRET_KEY.search(key):
        if not isinstance(value, str) or not ENV_REF.fullmatch(value):
            raise BindingRequired('INLINE_SECRET_FORBIDDEN_USE_ENV_REFERENCE')
    if isinstance(value, dict): return {k: _safe(v, str(k)) for k, v in value.items()}
    if isinstance(value, list): return [_safe(v, key) for v in value]
    if isinstance(value, str):
        if '{file:' in value: raise BindingRequired('SECRET_FILE_REFERENCE_REQUIRES_BANK_BINDING')
        if value.startswith(('http://', 'https://')):
            parsed = urlsplit(value)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise BindingRequired('CREDENTIAL_FREE_URL_REQUIRED')
    return value


def _module(spec, base, modules):
    """Resolve existing local modules only; npm downloads are never a fallback."""
    if not isinstance(spec, str): raise BindingRequired('LOCAL_MODULE_REFERENCE_REQUIRED')
    if spec.startswith('file://'):
        parsed = urlsplit(spec)
        if parsed.netloc not in ('', 'localhost'): raise BindingRequired('LOCAL_MODULE_REFERENCE_REQUIRED')
        raw = unquote(parsed.path)
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:/', raw): raw = raw[1:]
        path = Path(raw)
    elif spec.startswith(('.', '/', '~')) or re.match(r'^[A-Za-z]:[\\/]', spec):
        path = Path(spec).expanduser()
        if not path.is_absolute(): path = base / path
    else:
        # A package must already be installed next to the approved host config.
        package = spec.rsplit('@', 1)[0] if '@' in spec[1:] else spec
        if not re.fullmatch(r'(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+', package):
            raise BindingRequired('LOCAL_MODULE_REFERENCE_REQUIRED')
        folder = base / 'node_modules' / package
        manifest = _read_config(folder / 'package.json')
        exports = manifest.get('exports', {})
        entry = exports.get('.', exports) if isinstance(exports, dict) else exports
        while isinstance(entry, dict): entry = next((entry[k] for k in ('import', 'default', 'bun', 'node') if k in entry), None)
        entry = entry or manifest.get('module') or manifest.get('main') or 'index.js'
        if not isinstance(entry, str): raise BindingRequired('LOCAL_MODULE_ENTRY_REQUIRED')
        path = folder / entry
        if not path.resolve().is_relative_to(folder.resolve()): raise BindingRequired('LOCAL_MODULE_ENTRY_OUTSIDE_PACKAGE')
    path = path.resolve()
    if not path.is_file(): raise BindingRequired('OFFLINE_HOST_MODULE_MISSING')
    modules[str(path)] = digest(path)
    return path.as_uri()


def inspect_approved(path, approval_ref):
    if not str(approval_ref).strip(): raise BindingRequired('EXPLICIT_APPROVAL_REFERENCE_REQUIRED')
    cfg = _read_config(path)
    models = []
    providers = cfg.get('provider') or {}
    if not isinstance(providers, dict): raise BindingRequired('HOST_PROVIDER_OBJECT_REQUIRED')
    for provider, item in providers.items():
        if not IDENTIFIER.fullmatch(provider) or not isinstance(item, dict): continue
        model_map = item.get('models') or {}
        if not isinstance(model_map, dict): continue
        for model in model_map:
            if IDENTIFIER.fullmatch(model): models.append(provider + '/' + model)
    preferred = cfg.get('model')
    if isinstance(preferred, str) and IDENTIFIER.fullmatch(preferred) and preferred not in models: models.insert(0, preferred)
    return {'models': models, 'preferred_model': preferred if preferred in models else None,
            'host_auth_store_access': 'NONE', 'config_inspection': 'EXPLICITLY_APPROVED'}


def _selected(path, model_id):
    if not isinstance(model_id, str) or not IDENTIFIER.fullmatch(model_id) or '/' not in model_id:
        raise BindingRequired('PROVIDER_MODEL_ID_REQUIRED')
    provider_id, model_name = model_id.split('/', 1)
    cfg = _read_config(path)
    providers = cfg.get('provider') or {}
    if not isinstance(providers, dict): raise BindingRequired('HOST_PROVIDER_OBJECT_REQUIRED')
    provider = providers.get(provider_id)
    if not isinstance(provider, dict) or not isinstance(provider.get('models'), dict) or model_name not in provider['models']:
        raise BindingRequired('BANK_PROVIDER_BINDING_REQUIRED')
    # No host agent, tools, permissions, MCP, instructions, or auth-store import.
    selected = {k: v for k, v in provider.items() if k in {'name', 'api', 'env', 'npm', 'options'}}
    selected['models'] = {model_name: provider['models'][model_name]}
    selected = _safe(selected)
    modules = {}
    base = Path(path).expanduser().resolve().parent
    if selected.get('npm') and selected['npm'] not in BUNDLED_SDKS:
        selected['npm'] = _module(selected['npm'], base, modules)
    if not isinstance(selected['models'][model_name], dict): raise BindingRequired('HOST_MODEL_OBJECT_REQUIRED')
    per_model = selected['models'][model_name].get('provider', {})
    if not isinstance(per_model, dict): raise BindingRequired('HOST_MODEL_PROVIDER_OBJECT_REQUIRED')
    if per_model.get('npm') and per_model['npm'] not in BUNDLED_SDKS:
        per_model['npm'] = _module(per_model['npm'], base, modules)
    plugins = []
    specs = cfg.get('plugin') or []
    if not isinstance(specs, list): raise BindingRequired('HOST_PLUGIN_LIST_REQUIRED')
    specs = list(specs)
    # Global plugin auto-discovery would otherwise disappear with isolated XDG.
    for folder in ('plugin', 'plugins'):
        for extension in ('*.js', '*.ts', '*.mjs'):
            specs.extend(str(item) for item in sorted((base / folder).glob(extension)))
    for spec in specs:
        if isinstance(spec, list):
            if len(spec) != 2: raise BindingRequired('HOST_PLUGIN_SPEC_INVALID')
            plugins.append([_module(spec[0], base, modules), _safe(spec[1])])
        else: plugins.append(_module(spec, base, modules))
    config = {'model': model_id, 'small_model': model_id, 'enabled_providers': [provider_id],
              'provider': {provider_id: selected}}
    if plugins: config['plugin'] = plugins
    return config, modules


def create_binding(path, model_id, approval_ref):
    if not str(approval_ref).strip(): raise BindingRequired('EXPLICIT_APPROVAL_REFERENCE_REQUIRED')
    path = Path(path).expanduser().resolve()
    _, modules = _selected(path, model_id)
    return {'mode': 'REUSE_APPROVED_HOST_PROVIDER', 'source_path': str(path), 'model': model_id,
            'approval_ref': str(approval_ref).strip(), 'source_sha256': digest(path), 'module_sha256': modules,
            'credential_policy': 'ENV_REFERENCES_ONLY_NO_HOST_AUTH_READ',
            'qualification': 'PARTIAL_BANK_BINDING', 'bank_gate': 'BANK_PROVIDER_BINDING_REQUIRED'}


def resolve(binding):
    if binding.get('mode') != 'REUSE_APPROVED_HOST_PROVIDER' or not binding.get('approval_ref'):
        raise BindingRequired('EXPLICIT_APPROVAL_REFERENCE_REQUIRED')
    path = Path(binding.get('source_path', ''))
    if not path.is_file() or digest(path) != binding.get('source_sha256'):
        raise BindingRequired('HOST_CONFIG_CHANGED_REAPPROVAL_REQUIRED')
    config, modules = _selected(path, binding.get('model'))
    if modules != binding.get('module_sha256'):
        raise BindingRequired('HOST_MODULE_CHANGED_REAPPROVAL_REQUIRED')
    return config
