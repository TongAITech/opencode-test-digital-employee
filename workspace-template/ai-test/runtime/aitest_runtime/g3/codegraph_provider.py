from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import unquote, urlparse

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r3_2.contracts import ImpactEdge, RepositoryCompareRequest

_ALLOWED_STATES = {"AVAILABLE", "PARTIAL", "UNAVAILABLE", "BLOCKED"}


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    status: str
    version: str | None
    mode: str | None
    reason: str | None
    binary_sha256: str | None
    profile_digest: str | None

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATES:
            raise ValueError(f"unsupported provider state: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "status": self.status,
            "version": self.version,
            "mode": self.mode,
            "reason": self.reason,
            "binary_sha256": self.binary_sha256,
            "profile_digest": self.profile_digest,
        }


@dataclass(frozen=True)
class StructuralLineMapping:
    file_path: str
    line_number: int
    symbol_id: str
    symbol_name: str
    symbol_kind: str
    confidence: float
    provider_ref: str
    source_provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "symbol_id": self.symbol_id,
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "confidence": self.confidence,
            "provider_ref": self.provider_ref,
            "source_provenance": list(self.source_provenance),
        }


@dataclass(frozen=True)
class CodeGraphContribution:
    health: ProviderHealth
    mappings: tuple[StructuralLineMapping, ...] = ()
    impact_edges: tuple[ImpactEdge, ...] = ()
    warnings: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    graph_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": self.health.to_dict(),
            "mappings": [item.to_dict() for item in self.mappings],
            "impact_edges": [item.to_dict() for item in self.impact_edges],
            "warnings": list(self.warnings),
            "source_refs": list(self.source_refs),
            "graph_digest": self.graph_digest,
        }


class CodeGraphProvider(Protocol):
    @property
    def health(self) -> ProviderHealth: ...

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_executable_lines: Sequence[tuple[str, int]],
    ) -> CodeGraphContribution: ...


class UnavailableCodeGraphProvider:
    def __init__(self, health: ProviderHealth) -> None:
        self._health = health

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_executable_lines: Sequence[tuple[str, int]],
    ) -> CodeGraphContribution:
        warning = f"CODEGRAPH_{self._health.status}:{self._health.reason or 'UNAVAILABLE'}"
        return CodeGraphContribution(self._health, warnings=(warning,))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return _decode_jsonish(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            return value
    if isinstance(value, Mapping):
        result = {str(k): _decode_jsonish(v) for k, v in value.items()}
        content = result.get("content")
        if isinstance(content, list):
            decoded: list[Any] = []
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    decoded.append(_decode_jsonish(item["text"]))
                else:
                    decoded.append(item)
            result["content"] = decoded
        return result
    if isinstance(value, list):
        return [_decode_jsonish(item) for item in value]
    return value


def _walk_mappings(value: Any) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for item in value.values():
            found.extend(_walk_mappings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_mappings(item))
    return found


def _first_text(item: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(item: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _extract_symbol(payload: Any, file_path: str, line_number: int, provider_ref: str) -> StructuralLineMapping | None:
    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for item in _walk_mappings(payload):
        name = _first_text(item, ("symbolName", "symbol_name", "qualifiedName", "qualified_name", "name"))
        if not name:
            symbol_obj = item.get("symbol")
            if isinstance(symbol_obj, Mapping):
                name = _first_text(symbol_obj, ("name", "symbolName", "qualifiedName"))
                if name:
                    item = {**item, **{f"symbol_{key}": value for key, value in symbol_obj.items()}}
        if not name:
            continue
        start = _first_int(item, ("startLine", "start_line", "lineStart", "line_start", "line"))
        end = _first_int(item, ("endLine", "end_line", "lineEnd", "line_end"))
        score = 0
        for candidate_line in (line_number, line_number - 1):
            if start is not None and end is not None and start <= candidate_line <= end:
                score = max(score, 3)
            elif start is not None and start == candidate_line:
                score = max(score, 2)
        uri = _first_text(item, ("uri", "file", "filePath", "file_path", "path"))
        if uri and file_path.replace("\\", "/") in uri.replace("\\", "/"):
            score += 1
        if score:
            candidates.append((score, item))
    if not candidates:
        return None
    _, best = max(candidates, key=lambda pair: pair[0])
    name = _first_text(best, ("symbolName", "symbol_name", "qualifiedName", "qualified_name", "name")) or f"line-{line_number}"
    kind = (_first_text(best, ("symbolKind", "symbol_kind", "kind", "type")) or "SYMBOL").upper()
    node_id = _first_text(best, ("nodeId", "node_id", "symbolId", "symbol_id", "id"))
    symbol_id = f"{file_path}:{node_id or name}"
    provenance = (provider_ref, f"file:{file_path}:L{line_number}", "codegraph-tool:codegraph_get_ai_context")
    return StructuralLineMapping(file_path, line_number, symbol_id, name, kind, 0.95, provider_ref, provenance)


def _relative_file(raw: str | None, repo: Path) -> str | None:
    if not raw:
        return None
    value = raw
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        value = unquote(parsed.path)
        if os.name == "nt" and value.startswith("/") and len(value) > 2 and value[2] == ":":
            value = value[1:]
    try:
        path = Path(value)
        if path.is_absolute():
            return path.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        pass
    normalized = str(value).replace("\\", "/")
    marker = repo.name.replace("\\", "/") + "/"
    if marker in normalized:
        normalized = normalized.split(marker, 1)[1]
    return normalized.lstrip("/") or None


def _relationship_edges(
    payload: Any,
    *,
    repository_path: Path,
    source: StructuralLineMapping,
    edge_kind: str,
    direction: str,
    provider_ref: str,
    tool: str,
) -> list[ImpactEdge]:
    edges: list[ImpactEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for item in _walk_mappings(payload):
        location = item.get("location") if isinstance(item.get("location"), Mapping) else {}
        name = _first_text(item, ("symbolName", "symbol_name", "qualifiedName", "qualified_name", "name", "module", "dependency"))
        raw_path = _first_text(item, ("uri", "file", "filePath", "file_path", "path", "modulePath", "module_path"))
        if isinstance(location, Mapping):
            name = name or _first_text(location, ("name",))
            raw_path = raw_path or _first_text(location, ("uri", "file", "filePath", "file_path", "path"))
        node_id = _first_text(item, ("nodeId", "node_id", "symbolId", "symbol_id", "id"))
        rel = _relative_file(raw_path, repository_path)
        if not name and not rel and not node_id:
            continue
        line = _first_int(location if isinstance(location, Mapping) else item, ("line", "startLine", "start_line", "lineStart", "line_start"))
        stable = f"{rel}:{node_id or name or ('L' + str(line or 0))}" if rel else f"codegraph:{node_id or name}"
        if stable == source.symbol_id or (rel == source.file_path and name == source.symbol_name):
            continue
        depth = _first_int(item, ("depth", "distance")) or 1
        normalized_kinds = [edge_kind]
        impact_type = _first_text(item, ("impact_type", "impactType", "edge_type", "edgeType"))
        if edge_kind == "IMPACT" and impact_type and impact_type.strip().lower() in {"reference", "references"}:
            # CodeGraph v0.20.1 analyze_impact computes direct impact from all
            # incoming edge types and emits References as impact_type=reference.
            # Preserve IMPACT while also exposing the real REFERENCE relation.
            normalized_kinds.append("REFERENCE")
        for normalized_kind in normalized_kinds:
            key = (source.symbol_id, stable, normalized_kind)
            if key in seen:
                continue
            seen.add(key)
            provenance = [provider_ref, f"codegraph-tool:{tool}"]
            if rel:
                provenance.append(f"file:{rel}" + (f":L{line + 1}" if line is not None else ""))
            edges.append(
                ImpactEdge(
                    source.symbol_id,
                    stable,
                    normalized_kind,
                    direction,
                    depth,
                    0.98,
                    provider_ref,
                    tuple(provenance),
                )
            )
    return edges


class CodeGraphExecutableProvider:
    """Offline CodeGraph graph-only adapter.

    Git remains the sole changed-file/line authority. CodeGraph is structural
    enrichment only and is considered fully available only when all requested
    graph queries execute successfully.
    """

    PROVIDER_ID = "codegraph-ai/CodeGraph"

    def __init__(self, binary_path: Path, profile: Mapping[str, Any]) -> None:
        self.binary_path = Path(binary_path).resolve()
        self.profile = dict(profile)
        expected = str(self.profile.get("sha256") or "").lower()
        actual = _sha256_file(self.binary_path) if self.binary_path.is_file() else None
        profile_digest = canonical_sha256(self.profile)
        if not self.binary_path.is_file():
            status, reason = "UNAVAILABLE", "BINARY_NOT_FOUND"
        elif not expected:
            status, reason = "BLOCKED", "PINNED_SHA256_REQUIRED"
        elif actual != expected:
            status, reason = "BLOCKED", "BINARY_SHA256_MISMATCH"
        else:
            status, reason = "AVAILABLE", None
        self._health = ProviderHealth(
            self.PROVIDER_ID,
            status,
            str(self.profile.get("version") or "") or None,
            str(self.profile.get("mode") or "") or None,
            reason,
            actual,
            profile_digest,
        )

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def _run_tool(self, repo: Path, tool: str, args: Mapping[str, Any]) -> tuple[bool, Any, str | None]:
        proc = subprocess.run(
            [
                str(self.binary_path),
                "--graph-only",
                "--workspace",
                str(repo),
                "--run-tool",
                tool,
                "--tool-args",
                json.dumps(dict(args), ensure_ascii=False, separators=(",", ":")),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if proc.returncode != 0:
            return False, None, (proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}")[:500]
        raw = proc.stdout.strip()
        try:
            payload = _decode_jsonish(json.loads(raw))
        except json.JSONDecodeError:
            payload = _decode_jsonish(raw)
        return True, payload, None

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_executable_lines: Sequence[tuple[str, int]],
    ) -> CodeGraphContribution:
        if self._health.status != "AVAILABLE":
            return CodeGraphContribution(self._health, warnings=(f"CODEGRAPH_{self._health.status}:{self._health.reason}",))
        mappings: list[StructuralLineMapping] = []
        edges: list[ImpactEdge] = []
        warnings: list[str] = []
        source_refs: list[str] = []
        provider_ref = (
            f"codegraph:{self.PROVIDER_ID}:{self._health.version}:{self._health.mode}:"
            f"sha256={self._health.binary_sha256}"
        )
        source_refs.append(provider_ref)
        successful_mapping_calls = 0
        for file_path, line_number in changed_executable_lines:
            uri = (repository_path / file_path).resolve().as_uri()
            ok, payload, error = self._run_tool(
                repository_path,
                "codegraph_get_ai_context",
                {"uri": uri, "line": max(0, line_number - 1), "intent": "explain"},
            )
            if not ok:
                warnings.append(f"CODEGRAPH_QUERY_FAILED:get_ai_context:{file_path}:L{line_number}:{error}")
                continue
            successful_mapping_calls += 1
            mapping = _extract_symbol(payload, file_path, line_number, provider_ref)
            if mapping is None:
                warnings.append(f"CODEGRAPH_SYMBOL_UNRESOLVED:{file_path}:L{line_number}")
            else:
                mappings.append(mapping)

        unique: dict[str, StructuralLineMapping] = {}
        for mapping in mappings:
            unique.setdefault(mapping.symbol_id, mapping)

        structural_expected = 0
        structural_succeeded = 0
        structural_tools = (
            ("codegraph_get_callers", "CALLER", "INBOUND", lambda uri, line: {"uri": uri, "line": line, "depth": 1}),
            ("codegraph_get_callees", "CALLEE", "OUTBOUND", lambda uri, line: {"uri": uri, "line": line, "depth": 1}),
            ("codegraph_get_dependency_graph", "DEPENDENCY", "BOTH", lambda uri, line: {"uri": uri, "direction": "both", "depth": 1}),
            ("codegraph_analyze_impact", "IMPACT", "OUTBOUND", lambda uri, line: {"uri": uri, "line": line, "changeType": "modify"}),
        )
        for mapping in unique.values():
            uri = (repository_path / mapping.file_path).resolve().as_uri()
            line = max(0, mapping.line_number - 1)
            for tool, edge_kind, direction, args_factory in structural_tools:
                structural_expected += 1
                ok, payload, error = self._run_tool(repository_path, tool, args_factory(uri, line))
                if not ok:
                    warnings.append(f"CODEGRAPH_RELATIONSHIP_QUERY_FAILED:{tool}:{mapping.file_path}:L{mapping.line_number}:{error}")
                    continue
                structural_succeeded += 1
                source_refs.append(f"{provider_ref}:{tool}:{mapping.file_path}:L{mapping.line_number}")
                edges.extend(
                    _relationship_edges(
                        payload,
                        repository_path=repository_path,
                        source=mapping,
                        edge_kind=edge_kind,
                        direction=direction,
                        provider_ref=provider_ref,
                        tool=tool,
                    )
                )

        # A successful empty graph query is valid structural truth. A failed query
        # is not: it makes CodeGraph PARTIAL even when line->symbol mapping succeeded.
        mapping_complete = successful_mapping_calls == len(changed_executable_lines)
        structural_complete = structural_succeeded == structural_expected
        status = "AVAILABLE" if mapping_complete and structural_complete else "PARTIAL"
        reason = None if status == "AVAILABLE" else "ONE_OR_MORE_STRUCTURAL_OR_RELATIONSHIP_QUERIES_FAILED"
        health = ProviderHealth(
            self._health.provider_id,
            status,
            self._health.version,
            self._health.mode,
            reason,
            self._health.binary_sha256,
            self._health.profile_digest,
        )
        merged_edges: dict[tuple[str, str, str, str], ImpactEdge] = {}
        for edge in edges:
            merged_edges[(edge.from_node, edge.to_node, edge.edge_kind, edge.direction)] = edge
        graph_digest = canonical_sha256(
            {
                "provider": health.to_dict(),
                "compare": compare_request.to_dict(),
                "mappings": [item.to_dict() for item in mappings],
                "impact_edges": [item.to_dict() for item in merged_edges.values()],
                "relationship_queries": {
                    "expected": structural_expected,
                    "succeeded": structural_succeeded,
                    "tools": [item[0] for item in structural_tools],
                },
            }
        )
        return CodeGraphContribution(
            health,
            tuple(mappings),
            tuple(merged_edges.values()),
            tuple(dict.fromkeys(warnings)),
            tuple(dict.fromkeys(source_refs)),
            graph_digest,
        )


class CodeGraphProviderResolver:
    """Resolve the pinned offline CodeGraph payload without making it source truth."""

    @staticmethod
    def _runtime_lock(explicit: str | os.PathLike[str] | None = None) -> Path | None:
        candidates: list[Path] = []
        if explicit:
            candidates.append(Path(explicit))
        if os.environ.get("AITEST_RUNTIME_LOCK"):
            candidates.append(Path(os.environ["AITEST_RUNTIME_LOCK"]))
        for parent in Path(__file__).resolve().parents:
            candidates.append(parent / "runtime-lock.json")
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.is_file():
                return resolved
        return None

    @classmethod
    def resolve(cls, spec: Mapping[str, Any]) -> CodeGraphProvider:
        lock_path = cls._runtime_lock(spec.get("runtime_lock_path"))
        if lock_path is None:
            return UnavailableCodeGraphProvider(
                ProviderHealth("codegraph-ai/CodeGraph", "UNAVAILABLE", None, "graph-only", "RUNTIME_LOCK_UNAVAILABLE", None, None)
            )
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            profile = dict((lock.get("payloads") or {}).get("codegraph") or {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return UnavailableCodeGraphProvider(
                ProviderHealth("codegraph-ai/CodeGraph", "BLOCKED", None, "graph-only", "RUNTIME_LOCK_INVALID", None, None)
            )
        profile_digest = canonical_sha256(profile)
        if profile.get("provider") != "codegraph-ai/CodeGraph" or profile.get("mode") != "graph-only":
            return UnavailableCodeGraphProvider(
                ProviderHealth("codegraph-ai/CodeGraph", "BLOCKED", str(profile.get("version") or "") or None, str(profile.get("mode") or "") or None, "RUNTIME_LOCK_PROFILE_INVALID", None, profile_digest)
            )
        binary_override = spec.get("codegraph_binary_path") or os.environ.get("AITEST_CODEGRAPH_BINARY")
        if binary_override:
            binary = Path(str(binary_override))
        else:
            relative = str(profile.get("relative_target") or "")
            binary = lock_path.parent / relative if relative else Path("__missing_codegraph_binary__")
        provider = CodeGraphExecutableProvider(binary, profile)
        if provider.health.status == "AVAILABLE":
            return provider
        return UnavailableCodeGraphProvider(provider.health)