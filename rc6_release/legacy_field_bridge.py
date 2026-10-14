from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REGISTRY_REL = Path('aitest-runtime-context') / 'registry.json'
STATE_REL = Path('.dsh') / 'rc6' / 'LEGACY_FIELD_BRIDGE.json'

TOOL_BINDINGS: Dict[str, Dict[str, Any]] = {
    'codegraph': {
        'env': 'PFC_CODEGRAPH_BIN',
        'aliases': ('codegraph', 'code_graph'),
        'names': ('codegraph', 'codegraph.exe', 'codegraph.cmd', 'codegraph.bat', 'codegraph.ps1'),
    },
    'gitnexus': {
        'env': 'PFC_GITNEXUS_BIN',
        'aliases': ('gitnexus', 'git_nexus'),
        'names': ('gitnexus', 'gitnexus.exe', 'gitnexus.cmd', 'gitnexus.bat', 'git-nexus', 'git-nexus.cmd'),
    },
    'browserskill': {
        'env': 'PFC_BROWSERSKILL_BIN',
        'aliases': ('browserskill', 'browser_skill', 'browser-skill'),
        'names': (
            'browserskill', 'browserskill.exe', 'browserskill.cmd', 'browserskill.bat',
            'browser-skill', 'browser-skill.exe', 'browser-skill.cmd', 'browser-skill.bat',
        ),
    },
    'k6': {
        'env': 'PFC_K6_BIN',
        'aliases': ('k6',),
        'names': ('k6', 'k6.exe', 'k6.cmd'),
    },
    'zap': {
        'env': 'PFC_ZAP_BIN',
        'aliases': ('zap', 'zaproxy', 'owasp_zap'),
        'names': ('zap.exe', 'zap.bat', 'zap.cmd', 'zap.sh', 'zaproxy', 'zaproxy.exe', 'zaproxy.bat'),
    },
    'playwright': {
        'env': 'PFC_PLAYWRIGHT_BIN',
        'aliases': ('playwright',),
        'names': ('playwright', 'playwright.exe', 'playwright.cmd', 'playwright.bat'),
    },
    'chromium': {
        'env': 'PFC_CHROMIUM_BIN',
        'aliases': ('chromium', 'chrome', 'browser'),
        'names': ('chromium.exe', 'chromium', 'chrome.exe', 'chrome'),
    },
}

SPECIAL_BINDINGS = {
    '4a': {
        'env': 'PFC_4A_SCRIPT',
        'aliases': ('4a', 'foura', 'four_a'),
        'names': ('foura_auth.py', '4a_auth.py', 'foura-auth.py'),
    },
    'cat': {
        'env': 'PFC_CAT_CONFIG',
        'aliases': ('cat', 'cat_log', 'catlog'),
        'names': ('cat.json', 'cat.yml', 'cat.yaml', 'cat.properties', 'cat.url'),
    },
}


def _norm(value: Any) -> str:
    return ''.join(ch for ch in str(value).lower() if ch.isalnum())


def _aliases(spec: Dict[str, Any]) -> set[str]:
    return {_norm(x) for x in spec.get('aliases', ())}


def _identity_matches(mapping: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    aliases = _aliases(spec)
    for key in ('tool_id', 'tool', 'name', 'id', 'provider', 'capability', 'kind'):
        value = mapping.get(key)
        if value is not None and any(alias in _norm(value) for alias in aliases):
            return True
    return False


def _existing_candidate(value: str, workspace: Path, registry_root: Path) -> Optional[Path]:
    raw = str(value).strip().strip('"').strip("'")
    if not raw or len(raw) > 1024:
        return None
    direct = Path(raw).expanduser()
    for candidate in (direct, registry_root / raw, workspace / raw):
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            pass
    found = shutil.which(raw)
    if found:
        return Path(found).resolve()
    return None


def _registry_candidates(workspace: Path, tool_id: str, spec: Dict[str, Any]) -> Iterable[Path]:
    registry = workspace / REGISTRY_REL
    if not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return []
    aliases = _aliases(spec)
    found: List[Path] = []

    def walk(value: Any, ancestry: Sequence[str], inherited_match: bool = False) -> None:
        matched = inherited_match or any(alias in _norm(part) for alias in aliases for part in ancestry)
        if isinstance(value, dict):
            entity_match = matched or _identity_matches(value, spec)
            for key, child in value.items():
                walk(child, tuple(ancestry) + (str(key),), entity_match)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, tuple(ancestry) + (str(index),), matched)
        elif isinstance(value, str) and matched:
            path = _existing_candidate(value, workspace, registry.parent)
            if path is not None and path not in found:
                found.append(path)

    walk(data, ())
    return found


def _safe_roots(workspace: Path, package_root: Optional[Path]) -> List[Path]:
    roots = [
        workspace / 'aitest-runtime-context',
        workspace / 'cfg-ai-test-workspace-r1r4',
        workspace / '.pfc-r1r4' / 'releases',
        workspace / 'offline-tools',
        workspace / 'tools',
        workspace / '.tools',
        workspace / 'runtime',
        workspace / 'node_modules' / '.bin',
        workspace / '.opencode' / 'tools',
        workspace / '.dsh' / 'tools',
    ]
    if package_root is not None:
        roots.extend([
            package_root.parent,
            package_root.parent / 'tools',
            package_root.parent / 'offline-tools',
        ])
    unique: List[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in unique and resolved.is_dir():
            unique.append(resolved)
    return unique


def _bounded_name_search(roots: Sequence[Path], names: Sequence[str], max_depth: int = 7, max_entries: int = 30000) -> Optional[Path]:
    wanted = {name.lower() for name in names}
    visited = 0
    for root in roots:
        queue = deque([(root, 0)])
        while queue and visited < max_entries:
            current, depth = queue.popleft()
            try:
                entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for entry in entries:
                visited += 1
                if entry.is_file() and entry.name.lower() in wanted:
                    return entry.resolve()
                if depth < max_depth and entry.is_dir():
                    name = entry.name.lower()
                    if name in {'.git', '__pycache__', 'missions', 'evidence', 'reports'}:
                        continue
                    queue.append((entry, depth + 1))
                if visited >= max_entries:
                    break
    return None


def _discover(workspace: Path, package_root: Optional[Path], tool_id: str, spec: Dict[str, Any]) -> Tuple[Optional[Path], str]:
    # Existing explicit binding remains authoritative.
    env_value = os.environ.get(spec['env'])
    if env_value:
        path = _existing_candidate(env_value, workspace, workspace)
        if path is not None:
            return path, 'ENV:' + spec['env']

    # Historical runtime registry is next; it may point outside D:\\PFC.
    for candidate in _registry_candidates(workspace, tool_id, spec):
        return candidate, 'AITEST_RUNTIME_CONTEXT_REGISTRY'

    # Then scan only known runtime/tool roots, never the business repositories.
    path = _bounded_name_search(_safe_roots(workspace, package_root), spec['names'])
    if path is not None:
        return path, 'HISTORICAL_RUNTIME_ROOT'
    return None, 'NONE'


def build_bindings(workspace: str | Path, package_root: str | Path | None = None) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    package = Path(package_root).resolve() if package_root else None
    bindings: List[Dict[str, Any]] = []
    for tool_id, spec in TOOL_BINDINGS.items():
        path, provenance = _discover(work, package, tool_id, spec)
        bindings.append({
            'tool_id': tool_id,
            'env': spec['env'],
            'path': str(path) if path else None,
            'provenance': provenance,
            'found': path is not None,
        })

    # 4A/CAT are bindings, not boot-time READY claims. Never read CAT secret contents.
    for tool_id, spec in SPECIAL_BINDINGS.items():
        path, provenance = _discover(work, package, tool_id, spec)
        if tool_id == 'cat' and path is None:
            known = work / 'aitest-runtime-context' / 'secrets' / 'cat.json'
            if known.is_file():
                path, provenance = known.resolve(), 'AITEST_RUNTIME_CONTEXT_SECRET_REF'
        bindings.append({
            'tool_id': tool_id,
            'env': spec['env'],
            'path': str(path) if path else None,
            'provenance': provenance,
            'found': path is not None,
        })

    result = {
        'schema_version': 'pfc.aitest.rc6.legacy-field-bridge.v1',
        'workspace': str(work),
        'registry_path': str(work / REGISTRY_REL),
        'registry_present': (work / REGISTRY_REL).is_file(),
        'bindings': bindings,
        'summary': {
            'found': sum(1 for item in bindings if item['found']),
            'missing': sum(1 for item in bindings if not item['found']),
        },
        'secret_contents_read': False,
        'target_ready_forged': False,
    }
    state = work / STATE_REL
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.open('w', encoding='utf-8', newline='\n') as fh:
        json.dump(result, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write('\n')
    return result


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def write_env(workspace: str | Path, output: str | Path, package_root: str | Path | None = None) -> Dict[str, Any]:
    result = build_bindings(workspace, package_root)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# RC6 historical field bindings; generated without reading secret contents.']
    for item in result['bindings']:
        if item['found'] and item['path']:
            lines.append('export %s=%s' % (item['env'], _shell_quote(str(item['path']))))
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    result['env_file'] = str(target.resolve())
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m rc6_release.legacy_field_bridge')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--package-root')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    result = write_env(args.workspace, args.output, args.package_root)
    print(json.dumps({
        'status': 'PASS',
        'workspace': result['workspace'],
        'registry_present': result['registry_present'],
        'summary': result['summary'],
        'secret_contents_read': result['secret_contents_read'],
        'target_ready_forged': result['target_ready_forged'],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
