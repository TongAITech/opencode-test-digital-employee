from __future__ import annotations

import argparse
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

LEGACY_SCAN_ROOTS = (
    Path('.opencode') / 'skills',
    Path('.opencode') / 'agents',
)
STATE_REL = Path('.dsh') / 'rc6' / 'LEGACY_SKILL_GUARD.json'
BACKUP_ROOT = '.aitest-backup'


class LegacySkillGuardError(RuntimeError):
    pass


def _managed_entries(workspace: Path) -> List[Path]:
    result: List[Path] = []
    for rel in LEGACY_SCAN_ROOTS:
        root = workspace / rel
        if not root.is_dir():
            continue
        for item in sorted(root.iterdir()):
            if item.name.startswith('pfc-'):
                result.append(item)
    return result


def _rel(workspace: Path, path: Path) -> Path:
    return path.resolve().relative_to(workspace.resolve())


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(str(path))
    elif path.exists():
        path.unlink()


def _write_state(workspace: Path, value: Dict[str, Any]) -> None:
    path = workspace / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write('\n')


def sanitize_legacy_pfc_skills(workspace: str | Path) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    entries = _managed_entries(work)
    backup: Optional[Path] = None
    removed: List[str] = []
    if entries:
        backup = work / BACKUP_ROOT / (
            'rc6-legacy-skill-guard-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        )
        for item in entries:
            rel = _rel(work, item)
            _copy(item, backup / rel)
            removed.append(str(rel).replace('\\', '/'))
        for item in entries:
            _remove(item)
    result = {
        'status': 'PASS',
        'workspace': str(work),
        'legacy_pfc_skill_contamination': False,
        'removed_count': len(removed),
        'removed': removed,
        'backup_path': str(backup) if backup else None,
    }
    _write_state(work, result)
    verify_legacy_pfc_skills(work)
    return result


def verify_legacy_pfc_skills(workspace: str | Path) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    entries = _managed_entries(work)
    if entries:
        names = ','.join(str(_rel(work, item)).replace('\\', '/') for item in entries)
        raise LegacySkillGuardError('LEGACY_PFC_SKILL_CONTAMINATION:' + names)
    return {
        'status': 'PASS',
        'workspace': str(work),
        'legacy_pfc_skill_contamination': False,
    }


def rollback_legacy_pfc_skills(workspace: str | Path) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    state_path = work / STATE_REL
    if not state_path.is_file():
        return {'status': 'PASS', 'workspace': str(work), 'restored_count': 0, 'restored_from': None}
    state = json.loads(state_path.read_text(encoding='utf-8'))
    backup_value = state.get('backup_path')
    if not backup_value:
        return {'status': 'PASS', 'workspace': str(work), 'restored_count': 0, 'restored_from': None}
    backup = Path(str(backup_value)).resolve()
    if not backup.is_dir():
        raise LegacySkillGuardError('LEGACY_SKILL_GUARD_BACKUP_NOT_FOUND')
    restored = 0
    for rel in LEGACY_SCAN_ROOTS:
        source_root = backup / rel
        if not source_root.is_dir():
            continue
        target_root = work / rel
        target_root.mkdir(parents=True, exist_ok=True)
        for item in source_root.iterdir():
            dst = target_root / item.name
            if dst.exists():
                _remove(dst)
            _copy(item, dst)
            restored += 1
    return {
        'status': 'PASS',
        'workspace': str(work),
        'restored_count': restored,
        'restored_from': str(backup),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m rc6_release.legacy_skill_guard')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('sanitize', 'verify', 'rollback'):
        p = sub.add_parser(name)
        p.add_argument('--workspace', required=True)
    args = parser.parse_args(argv)
    if args.command == 'sanitize':
        result = sanitize_legacy_pfc_skills(args.workspace)
    elif args.command == 'verify':
        result = verify_legacy_pfc_skills(args.workspace)
    else:
        result = rollback_legacy_pfc_skills(args.workspace)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
