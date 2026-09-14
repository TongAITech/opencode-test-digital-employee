from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r3_2.contracts import ImpactEdge, ImpactedSurface, RepositoryCompareRequest

_ALLOWED_STATES = {"AVAILABLE", "PARTIAL", "UNAVAILABLE", "BLOCKED"}


@dataclass(frozen=True)
class GitNexusHealth:
    provider_id: str
    status: str
    version: str | None
    reason: str | None
    cli_sha256: str | None
    tree_sha256: str | None

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATES:
            raise ValueError(f"unsupported GitNexus state: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "status": self.status,
            "version": self.version,
            "reason": self.reason,
            "cli_sha256": self.cli_sha256,
            "tree_sha256": self.tree_sha256,
        }


@dataclass(frozen=True)
class GitNexusContribution:
    health: GitNexusHealth
    impact_edges: tuple[ImpactEdge, ...] = ()
    impacted_surfaces: tuple[ImpactedSurface, ...] = ()
    warnings: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    graph_digest: str | None = None
    page_impacts: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": self.health.to_dict(),
            "impact_edges": [item.to_dict() for item in self.impact_edges],
            "impacted_surfaces": [item.to_dict() for item in self.impacted_surfaces],
            "warnings": list(self.warnings),
            "source_refs": list(self.source_refs),
            "graph_digest": self.graph_digest,
            "page_impacts": [dict(item) for item in self.page_impacts],
        }


class UnavailableGitNexusProvider:
    def __init__(self, health: GitNexusHealth) -> None:
        self.health = health

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_vue_paths: Sequence[str],
    ) -> GitNexusContribution:
        if not changed_vue_paths:
            return GitNexusContribution(self.health)
        warning = f"GITNEXUS_{self.health.status}:{self.health.reason or 'UNAVAILABLE'}"
        return GitNexusContribution(self.health, warnings=(warning,))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_lock_path(lock_root: Path, relative: str) -> Path:
    relative_path = Path(relative.replace("\\", "/"))
    candidates = [lock_root / relative_path]
    parts = relative_path.parts
    if parts and parts[0] == "workspace-template":
        candidates.append(lock_root / Path(*parts[1:]))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def _json_stdout(stdout: str) -> Mapping[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("empty GitNexus output")
    try:
        value = json.loads(text)
        if isinstance(value, Mapping):
            return value
    except json.JSONDecodeError:
        pass
    starts = [index for index, char in enumerate(text) if char == "{"]
    for index in reversed(starts):
        try:
            value = json.loads(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ValueError("GitNexus JSON output missing")


def _markdown_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    markdown = payload.get("markdown")
    if not isinstance(markdown, str):
        return []
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    headers = [value.strip() for value in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        values = [value.strip() for value in line.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def _is_page_file(path: str) -> bool:
    low = "/" + path.replace("\\", "/").lower().lstrip("/")
    return "/pages/" in low or "/views/" in low


class GitNexusExecutableProvider:
    provider_id = "abhigyanpatwari/GitNexus"

    def __init__(
        self,
        *,
        node_path: Path,
        cli_path: Path,
        version: str,
        expected_cli_sha256: str,
        tree_sha256: str | None,
        home_root: Path | None = None,
    ) -> None:
        self.node_path = node_path.resolve()
        self.cli_path = cli_path.resolve()
        self.version = version
        self.expected_cli_sha256 = expected_cli_sha256
        self.tree_sha256 = tree_sha256
        self.home_root = home_root.resolve() if home_root else None

    @property
    def health(self) -> GitNexusHealth:
        if not self.node_path.is_file():
            return GitNexusHealth(self.provider_id, "UNAVAILABLE", self.version, "NODE_MISSING", None, self.tree_sha256)
        if not self.cli_path.is_file():
            return GitNexusHealth(self.provider_id, "UNAVAILABLE", self.version, "CLI_MISSING", None, self.tree_sha256)
        actual = _sha256_file(self.cli_path)
        if actual != self.expected_cli_sha256:
            return GitNexusHealth(self.provider_id, "BLOCKED", self.version, "CLI_SHA256_MISMATCH", actual, self.tree_sha256)
        return GitNexusHealth(self.provider_id, "AVAILABLE", self.version, None, actual, self.tree_sha256)

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        home: Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() not in {
                "NODE_OPTIONS",
                "NPM_CONFIG_PREFIX",
                "NPM_CONFIG_REGISTRY",
                "GITNEXUS_AUTH_TOKEN",
            }
        }
        env.update(
            {
                "GITNEXUS_HOME": str(home),
                "GITNEXUS_NO_UPDATE_NOTIFIER": "1",
                "NO_UPDATE_NOTIFIER": "1",
                "CI": "1",
                "NO_COLOR": "1",
            }
        )
        return subprocess.run(
            [str(self.node_path), str(self.cli_path), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_vue_paths: Sequence[str],
    ) -> GitNexusContribution:
        health = self.health
        if not changed_vue_paths:
            return GitNexusContribution(health)
        if health.status != "AVAILABLE":
            return UnavailableGitNexusProvider(health).analyze(
                repository_path, compare_request, changed_vue_paths
            )

        repo = repository_path.resolve()
        home_base = self.home_root or Path(tempfile.gettempdir()) / "aitest-gitnexus"
        identity = canonical_sha256(
            {
                "repo": str(repo),
                "base": compare_request.base_sha,
                "head": compare_request.head_sha,
                "version": self.version,
            }
        )[:24]
        home = (home_base / identity).resolve()
        home.mkdir(parents=True, exist_ok=True)
        repo_name = f"aitest-{canonical_sha256(str(repo))[:16]}"

        analyze = self._run(
            [
                "analyze",
                str(repo),
                "--index-only",
                "--skip-fts",
                "--skip-skills",
                "--skip-agents-md",
                "--name",
                repo_name,
            ],
            cwd=repo,
            home=home,
            timeout=600,
        )
        if analyze.returncode != 0:
            reason = (analyze.stderr or analyze.stdout).strip()[-1000:] or "ANALYZE_FAILED"
            partial = GitNexusHealth(
                self.provider_id,
                "PARTIAL",
                self.version,
                f"ANALYZE_FAILED:{reason}",
                health.cli_sha256,
                self.tree_sha256,
            )
            return GitNexusContribution(
                partial,
                warnings=("GITNEXUS_ANALYZE_FAILED",),
            )

        query = (
            "MATCH (a:File)-[r:CodeRelation {type: 'CALLS'}]->(b:File) "
            "WHERE r.reason = 'vue-template-component' "
            "RETURN a.filePath AS source, b.filePath AS target, r.reason AS reason LIMIT 10000"
        )
        graph = self._run(
            ["cypher", query, "--repo", repo_name],
            cwd=repo,
            home=home,
            timeout=120,
        )
        if graph.returncode != 0:
            reason = (graph.stderr or graph.stdout).strip()[-1000:] or "QUERY_FAILED"
            partial = GitNexusHealth(
                self.provider_id,
                "PARTIAL",
                self.version,
                f"QUERY_FAILED:{reason}",
                health.cli_sha256,
                self.tree_sha256,
            )
            return GitNexusContribution(
                partial,
                warnings=("GITNEXUS_VUE_COMPONENT_QUERY_FAILED",),
            )

        try:
            payload = _json_stdout(graph.stdout)
            rows = _markdown_rows(payload)
        except (ValueError, TypeError) as exc:
            partial = GitNexusHealth(
                self.provider_id,
                "PARTIAL",
                self.version,
                f"OUTPUT_INVALID:{type(exc).__name__}",
                health.cli_sha256,
                self.tree_sha256,
            )
            return GitNexusContribution(
                partial,
                warnings=("GITNEXUS_OUTPUT_INVALID",),
            )

        reverse: dict[str, set[str]] = {}
        normalized_rows: list[dict[str, str]] = []
        for row in rows:
            source = str(row.get("source") or "").replace("\\", "/").strip()
            target = str(row.get("target") or "").replace("\\", "/").strip()
            reason = str(row.get("reason") or "").strip()
            if not source or not target or reason != "vue-template-component":
                continue
            reverse.setdefault(target, set()).add(source)
            normalized_rows.append({"source": source, "target": target, "reason": reason})

        edges: list[ImpactEdge] = []
        surfaces: list[ImpactedSurface] = []
        page_impacts: list[Mapping[str, Any]] = []
        evidence_refs: list[str] = []
        seen_edges: set[tuple[str, str]] = set()
        seen_pages: set[tuple[str, str]] = set()
        changed = tuple(dict.fromkeys(path.replace("\\", "/") for path in changed_vue_paths))

        for changed_path in changed:
            queue: list[tuple[str, int]] = [(changed_path, 0)]
            visited = {changed_path}
            while queue:
                target, depth = queue.pop(0)
                for consumer in sorted(reverse.get(target, ())):
                    if consumer in visited:
                        continue
                    visited.add(consumer)
                    next_depth = depth + 1
                    evidence = f"gitnexus:vue-template-component:{consumer}->{target}"
                    edge_key = (changed_path, consumer)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append(
                            ImpactEdge(
                                changed_path,
                                consumer,
                                "COMPONENT_CONSUMER",
                                "OUTBOUND",
                                next_depth,
                                0.95,
                                f"gitnexus:{self.version}",
                                (
                                    evidence,
                                    f"git:{compare_request.base_sha}..{compare_request.head_sha}",
                                ),
                            )
                        )
                    evidence_refs.append(evidence)
                    if _is_page_file(consumer):
                        page_key = (changed_path, consumer)
                        if page_key not in seen_pages:
                            seen_pages.add(page_key)
                            surfaces.append(
                                ImpactedSurface(
                                    "PAGE",
                                    consumer,
                                    "VUE_COMPONENT_CONSUMER",
                                    0.95,
                                    (evidence,),
                                )
                            )
                            page_impacts.append(
                                {
                                    "changed_component": changed_path,
                                    "affected_page_file": consumer,
                                    "depth": next_depth,
                                    "relation": "VUE_COMPONENT_CONSUMER",
                                    "evidence_ref": evidence,
                                }
                            )
                    queue.append((consumer, next_depth))

        source_refs = [
            f"gitnexus:{self.version}:index:{repo_name}",
            f"gitnexus:{self.version}:code-relation:vue-template-component",
            *evidence_refs,
        ]
        graph_digest = canonical_sha256(
            {
                "provider": self.provider_id,
                "version": self.version,
                "repository": compare_request.repository_id,
                "base_sha": compare_request.base_sha,
                "head_sha": compare_request.head_sha,
                "rows": normalized_rows,
            }
        )
        warnings: list[str] = []
        if not surfaces:
            warnings.append("GITNEXUS_VUE_PAGE_IMPACT_UNRESOLVED")

        return GitNexusContribution(
            health,
            tuple(edges),
            tuple(surfaces),
            tuple(warnings),
            tuple(dict.fromkeys(source_refs)),
            graph_digest,
            tuple(page_impacts),
        )


class GitNexusProviderResolver:
    @staticmethod
    def resolve(spec: Mapping[str, Any]) -> GitNexusExecutableProvider | UnavailableGitNexusProvider:
        explicit_node = spec.get("gitnexus_node_path")
        explicit_cli = spec.get("gitnexus_cli_path")
        lock_raw = spec.get("runtime_lock_path")
        lock_path = Path(str(lock_raw)).resolve() if lock_raw else None
        lock: Mapping[str, Any] = {}
        if lock_path and lock_path.is_file():
            try:
                decoded = json.loads(lock_path.read_text(encoding="utf-8"))
                if isinstance(decoded, Mapping):
                    lock = decoded
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass

        profiles = lock.get("payloads") if isinstance(lock.get("payloads"), Mapping) else {}
        node_profile = profiles.get("node") if isinstance(profiles.get("node"), Mapping) else {}
        profile = profiles.get("gitnexus") if isinstance(profiles.get("gitnexus"), Mapping) else {}
        version = str(profile.get("version") or "1.6.12")
        expected_cli_sha = str(profile.get("sha256") or "")
        tree_sha = str(profile.get("tree_sha256") or "") or None
        if not expected_cli_sha:
            return UnavailableGitNexusProvider(
                GitNexusHealth(
                    "abhigyanpatwari/GitNexus",
                    "UNAVAILABLE",
                    version,
                    "RUNTIME_LOCK_PROFILE_MISSING",
                    None,
                    tree_sha,
                )
            )

        if explicit_node:
            node = Path(str(explicit_node)).resolve()
        elif lock_path and node_profile.get("relative_target"):
            node = _resolve_lock_path(lock_path.parent, str(node_profile["relative_target"]))
        else:
            node = Path("__missing_gitnexus_node__").resolve()

        if explicit_cli:
            cli = Path(str(explicit_cli)).resolve()
        elif lock_path and profile.get("relative_target"):
            cli = _resolve_lock_path(lock_path.parent, str(profile["relative_target"]))
        else:
            cli = Path("__missing_gitnexus_cli__").resolve()

        home_raw = spec.get("gitnexus_home")
        return GitNexusExecutableProvider(
            node_path=node,
            cli_path=cli,
            version=version,
            expected_cli_sha256=expected_cli_sha,
            tree_sha256=tree_sha,
            home_root=Path(str(home_raw)) if home_raw else None,
        )
