"""Targeted dependency invalidation for RC7 artifacts.

An upstream revision change must not restart the whole Mission.  The dependency
graph computes the minimal downstream closure and marks only affected artifacts
and previously accepted tasks for revalidation.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Set, Tuple

from .models import Artifact, Task, TaskStatus
from .state_machine import invalidate_artifact, transition_task


class DependencyError(ValueError):
    pass


@dataclass(frozen=True)
class InvalidationResult:
    changed_refs: Tuple[str, ...]
    affected_artifact_ids: Tuple[str, ...]
    stale_task_ids: Tuple[str, ...]


class ArtifactDependencyGraph:
    def __init__(self) -> None:
        self._downstream: MutableMapping[str, Set[str]] = defaultdict(set)

    def add(self, upstream_ref: str, downstream_ref: str) -> None:
        upstream = self._required(upstream_ref, "UPSTREAM_REF")
        downstream = self._required(downstream_ref, "DOWNSTREAM_REF")
        if upstream == downstream:
            raise DependencyError("SELF_DEPENDENCY_FORBIDDEN")
        if self._reachable(downstream, upstream):
            raise DependencyError("DEPENDENCY_CYCLE_FORBIDDEN")
        self._downstream[upstream].add(downstream)

    def register_artifact(self, artifact: Artifact) -> None:
        for parent_ref in artifact.parent_refs:
            self.add(parent_ref, artifact.artifact_id)

    def descendants(self, refs: Iterable[str]) -> Tuple[str, ...]:
        roots = [self._required(ref, "CHANGED_REF") for ref in refs]
        seen: Set[str] = set()
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            for child in sorted(self._downstream.get(current, set())):
                if child in seen or child in roots:
                    continue
                seen.add(child)
                queue.append(child)
        return tuple(sorted(seen))

    def invalidate(
        self,
        changed_refs: Iterable[str],
        artifacts: Mapping[str, Artifact],
        tasks: Iterable[Task] = (),
    ) -> InvalidationResult:
        changed = tuple(sorted(set(self._required(ref, "CHANGED_REF") for ref in changed_refs)))
        affected = self.descendants(changed)
        affected_set = set(affected)

        for artifact_id in affected:
            artifact = artifacts.get(artifact_id)
            if artifact is not None:
                invalidate_artifact(artifact, require_revalidation=True)

        stale_tasks: List[str] = []
        for task in tasks:
            if task.state != TaskStatus.PASS:
                continue
            refs = set(task.input_artifact_refs) | set(task.output_artifact_refs)
            if refs.intersection(affected_set) or refs.intersection(changed):
                transition_task(task, TaskStatus.STALE)
                stale_tasks.append(task.task_id)

        return InvalidationResult(
            changed_refs=changed,
            affected_artifact_ids=affected,
            stale_task_ids=tuple(sorted(stale_tasks)),
        )

    def _reachable(self, start: str, target: str) -> bool:
        if start == target:
            return True
        queue = deque([start])
        seen = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            for child in self._downstream.get(current, set()):
                if child == target:
                    return True
                queue.append(child)
        return False

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DependencyError("%s_REQUIRED" % name)
        return value.strip()
