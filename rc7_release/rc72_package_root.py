"""Resolve an RC7.2 package root after single- or nested-folder extraction.

The resolver is intentionally marker-based and bounded. It never guesses from
folder names and refuses ambiguous extraction trees.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Optional

_SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
_MARKERS = (
    "SOURCE_COMMIT",
    "PACKAGE_MANIFEST.json",
    "RC72_RELEASE_IDENTITY.json",
    "workspace-template/runtime/python/python.exe",
    "packaging/rc7.2/AITEST.sh",
)


class PackageRootResolutionError(RuntimeError):
    pass


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _is_package_root(candidate: Path) -> bool:
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            return False
        root = candidate.resolve(strict=True)
        marker_paths = []
        for relative in _MARKERS:
            marker = candidate / relative
            if marker.is_symlink() or not marker.is_file():
                return False
            resolved = marker.resolve(strict=True)
            if not _inside(root, resolved):
                return False
            marker_paths.append(marker)
        source_commit = marker_paths[0].read_text(encoding="utf-8").strip().lower()
        if not _SOURCE_RE.fullmatch(source_commit):
            return False
        identity = json.loads(marker_paths[2].read_text(encoding="utf-8"))
        return identity.get("source_commit") == source_commit
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def _ancestors(path: Path, limit: int = 10) -> Iterable[Path]:
    current = path
    for _ in range(limit + 1):
        yield current
        parent = current.parent
        if parent == current:
            break
        current = parent


def _descendant_roots(start: Path, max_depth: int) -> List[Path]:
    found: List[Path] = []
    frontier = [start]
    for _ in range(max_depth):
        next_frontier: List[Path] = []
        for parent in frontier:
            try:
                children = sorted(
                    (child for child in parent.iterdir()
                     if child.is_dir() and not child.is_symlink()),
                    key=lambda item: item.name.lower(),
                )
            except OSError:
                continue
            for child in children:
                if _is_package_root(child):
                    found.append(child.resolve())
                else:
                    next_frontier.append(child)
        frontier = next_frontier
        if not frontier:
            break
    return found


def resolve_package_root(
    value: Path,
    *,
    max_ancestor_depth: int = 10,
    max_nested_depth: int = 3,
) -> Path:
    """Return the one verified package root represented by *value*.

    Accepts the package root, a launcher/directory inside it, or an outer
    extraction directory containing one nested package root. Ambiguous trees
    fail closed.
    """
    start = Path(value).expanduser()
    if not start.exists():
        raise PackageRootResolutionError("RC72_PACKAGE_ROOT_INPUT_NOT_FOUND")
    if start.is_file():
        start = start.parent
    try:
        start = start.resolve(strict=True)
    except OSError as exc:
        raise PackageRootResolutionError("RC72_PACKAGE_ROOT_INPUT_UNRESOLVABLE") from exc

    if _is_package_root(start):
        return start

    for ancestor in _ancestors(start.parent, max_ancestor_depth):
        if _is_package_root(ancestor):
            return ancestor.resolve()

    nested = sorted(set(_descendant_roots(start, max_nested_depth)))
    if len(nested) == 1:
        return nested[0]
    if len(nested) > 1:
        raise PackageRootResolutionError("RC72_PACKAGE_ROOT_AMBIGUOUS")
    raise PackageRootResolutionError("RC72_PACKAGE_ROOT_NOT_FOUND")
