from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import canonical_sha256

from .contracts import (
    ChangedFileFact,
    ChangedSymbolFact,
    CodeIntelligenceEnvelope,
    CompareIdentity,
    ImpactEdge,
    ImpactedSurface,
    R32Error,
    RepositoryCompareRequest,
)


DEFAULT_CAPABILITIES = (
    "changed_files",
    "changed_symbols",
    "call_chain",
    "impacted_surfaces",
)


class CodeIntelligenceProvider(Protocol):
    def collect(
        self,
        repository: RepositoryCompareRequest,
        code_intelligence: Mapping[str, Any],
        *,
        policy_version: str,
    ) -> CodeIntelligenceEnvelope:
        ...


def _run_git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise R32Error("R3_2_PROVIDER_UNAVAILABLE", f"git provider unavailable: {exc}") from exc
    if result.returncode != 0:
        raise R32Error("R3_2_PROVIDER_UNAVAILABLE", result.stderr.strip() or "git provider command failed")
    return result.stdout


def _try_git(root: Path, args: list[str]) -> str | None:
    try:
        return _run_git(root, args)
    except R32Error:
        return None


def _commit(root: Path, value: str | None) -> str | None:
    if not value:
        return None
    output = _try_git(root, ["rev-parse", "--verify", value])
    return output.strip() if output else None


def _blob(root: Path, revision: str | None, path: str, *, working_tree: bool = False) -> str | None:
    if working_tree:
        output = _try_git(root, ["hash-object", "--", path])
    elif revision:
        output = _try_git(root, ["rev-parse", f"{revision}:{path}"])
    else:
        output = None
    return output.strip() if output else None


def _parse_name_status(output: str) -> list[tuple[str, str | None, str | None]]:
    tokens = [token for token in output.split("\0") if token]
    result: list[tuple[str, str | None, str | None]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        code = status[0]
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise R32Error("R3_2_PROVIDER_OUTPUT_INVALID", "rename/copy diff lacks both paths")
            old_path, new_path = tokens[index], tokens[index + 1]
            index += 2
            result.append((code, old_path, new_path))
        else:
            if index >= len(tokens):
                raise R32Error("R3_2_PROVIDER_OUTPUT_INVALID", "file diff lacks path")
            path = tokens[index]
            index += 1
            result.append((code, None if code == "A" else path, None if code == "D" else path))
    return result


def _changed_lines(diff_output: str) -> dict[str, tuple[int, ...]]:
    result: dict[str, list[int]] = {}
    current_path: str | None = None
    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if line.startswith("@@") and current_path:
            match = re.search(r"\+([0-9]+)(?:,([0-9]+))?", line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            result.setdefault(current_path, []).extend(range(start, start + max(count, 1)))
    return {path: tuple(sorted(set(lines))) for path, lines in result.items()}


def _diff_line_counts(diff_output: str) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    current_path: str | None = None
    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            counts.setdefault(current_path, [0, 0])
            continue
        if not current_path or line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            counts[current_path][0] += 1
        elif line.startswith("-"):
            counts[current_path][1] += 1
    return {path: (value[0], value[1]) for path, value in counts.items()}


def _definition_signature(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _python_symbols(path: str, source: str, changed_lines: tuple[int, ...]) -> tuple[ChangedSymbolFact, list[tuple[str, ast.AST]], list[str]]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return (), [], [f"python parse failed for {path}: {exc.msg} at line {exc.lineno}"]
    line_set = set(changed_lines)
    symbols: list[ChangedSymbolFact] = []
    nodes: list[tuple[str, ast.AST]] = []
    warnings: list[str] = []

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                symbol_id = f"{path}::{name}"
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                if not line_set or any(start <= line <= end for line in line_set):
                    kind = "CLASS" if isinstance(node, ast.ClassDef) else "FUNCTION"
                    symbols.append(
                        ChangedSymbolFact(
                            symbol_id=symbol_id,
                            file_path=path,
                            symbol_kind=kind,
                            change_kind="MODIFIED",
                            old_signature=None,
                            new_signature=_definition_signature(node),
                            line_refs=tuple(sorted(line for line in line_set if start <= line <= end)) or (start,),
                            source_provenance=(),
                        )
                    )
                    nodes.append((symbol_id, node))
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue

    visit(tree.body)
    return tuple(symbols), nodes, warnings


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _python_edges(
    symbols: tuple[ChangedSymbolFact, ...],
    nodes: list[tuple[str, ast.AST]],
    provider_ref: str,
    provenance: tuple[str, ...],
) -> tuple[ImpactEdge, ...]:
    known = {item.symbol_id.rsplit("::", 1)[-1]: item.symbol_id for item in symbols}
    edges: list[ImpactEdge] = []
    for source_id, node in nodes:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            target_name = _call_name(child)
            if not target_name:
                continue
            target = known.get(target_name) or f"unresolved::{target_name}"
            edges.append(
                ImpactEdge(
                    from_node=source_id,
                    to_node=target,
                    edge_kind="CALLS",
                    direction="DOWNSTREAM",
                    depth=1,
                    confidence=0.9 if target in known.values() else 0.35,
                    provider_ref=provider_ref,
                    source_provenance=provenance,
                )
            )
    return tuple(edges)


def _python_signature_map(source: str, path: str) -> dict[str, str]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {}
    result: dict[str, str] = {}

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                result[f"{path}::{name}"] = _definition_signature(node)
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name)

    visit(tree.body)
    return result


def _python_surfaces(
    symbols: tuple[ChangedSymbolFact, ...],
    nodes: list[tuple[str, ast.AST]],
    provenance: tuple[str, ...],
) -> tuple[ImpactedSurface, ...]:
    surfaces: list[ImpactedSurface] = []
    for symbol_id, node in nodes:
        decorators = getattr(node, "decorator_list", ())
        for decorator in decorators:
            name: str | None = None
            path_value: str | None = None
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    name = decorator.func.id
                elif isinstance(decorator.func, ast.Attribute):
                    name = decorator.func.attr
                if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                    path_value = decorator.args[0].value
            elif isinstance(decorator, ast.Name):
                name = decorator.id
            if name and name.lower() in {"get", "post", "put", "patch", "delete", "route"} and path_value:
                surfaces.append(
                    ImpactedSurface(
                        surface_kind="API",
                        stable_surface_id=f"api:{path_value}",
                        relation="ROUTE_DECORATOR",
                        confidence=0.9,
                        evidence_refs=provenance + (f"symbol:{symbol_id}",),
                    )
                )
    unique: dict[str, ImpactedSurface] = {item.stable_surface_id: item for item in surfaces}
    return tuple(unique[key] for key in sorted(unique))


def _status_digest(root: Path) -> str | None:
    output = _try_git(root, ["status", "--porcelain=v1", "-uall"])
    return canonical_sha256(output.splitlines()) if output is not None else None


class GitCodeIntelligenceProvider:
    """Explicit Git diff plus conservative Python symbol/call evidence provider.

    It reports PARTIAL whenever the requested static evidence cannot be resolved. A file
    diff alone never upgrades a change obligation to RESOLVED.
    """

    provider_id = "git-static-code-intelligence"
    provider_version = "1"

    def collect(
        self,
        repository: RepositoryCompareRequest,
        code_intelligence: Mapping[str, Any],
        *,
        policy_version: str,
    ) -> CodeIntelligenceEnvelope:
        provider_id = str(code_intelligence["provider_id"])
        provider_version = str(code_intelligence["provider_version"])
        requested = tuple(str(item) for item in code_intelligence["requested_capabilities"])
        input_digest = str(code_intelligence["provider_input_digest"])
        root = Path(repository.repository_path) if repository.repository_path else None
        if root is None or not root.exists():
            return self._unavailable(repository, provider_id, provider_version, requested, input_digest, policy_version, "repository_path is not available")
        top = _try_git(root, ["rev-parse", "--show-toplevel"])
        if not top:
            return self._unavailable(repository, provider_id, provider_version, requested, input_digest, policy_version, "repository is not a Git worktree")
        try:
            compare_args, base_sha, head_sha = self._compare_args(root, repository)
            diff = _run_git(root, ["diff", "--no-ext-diff", "--find-renames", "--unified=0", *compare_args, "--"])
            names = _parse_name_status(_run_git(root, ["diff", "--no-ext-diff", "--find-renames", "--name-status", "-z", *compare_args, "--"]))
            status_digest = _status_digest(root) if repository.compare_mode == "WORKING_TREE" else repository.working_tree_status_digest
            if repository.compare_mode == "WORKING_TREE" and status_digest != repository.working_tree_status_digest:
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "working_tree_status_digest does not match repository")
        except R32Error as exc:
            return self._unavailable(repository, provider_id, provider_version, requested, input_digest, policy_version, str(exc))

        changed_lines = _changed_lines(diff)
        line_counts = _diff_line_counts(diff)
        facts: list[ChangedFileFact] = []
        warnings: list[str] = []
        for status, old_path, new_path in names:
            change_kind = {"A": "ADDED", "M": "MODIFIED", "D": "DELETED", "R": "RENAMED", "C": "COPIED", "T": "TYPE_CHANGED"}.get(status[0], "MODIFIED")
            path = new_path or old_path
            if not path:
                continue
            facts.append(
                ChangedFileFact(
                    file_path=path, change_kind=change_kind, old_path=old_path, new_path=new_path,
                    old_sha=_blob(root, base_sha, old_path or path), new_sha=_blob(root, head_sha, new_path or path, working_tree=repository.compare_mode == "WORKING_TREE"),
                    lines_added=line_counts.get(path, (0, 0))[0], lines_deleted=line_counts.get(path, (0, 0))[1],
                    diff_hunk_refs=tuple(f"{path}:{line}" for line in changed_lines.get(path, ())), source_provenance=(),
                )
            )

        include_untracked = repository.untracked_policy != "EXCLUDE"
        if include_untracked:
            candidates = list(repository.untracked_paths)
            if repository.untracked_policy == "INCLUDE":
                status_output = _run_git(root, ["status", "--porcelain=v1", "-uall"])
                candidates.extend(line[3:] for line in status_output.splitlines() if line.startswith("?? "))
            known_paths = {item.file_path for item in facts}
            for path in sorted(set(candidates) - known_paths):
                if not (root / path).is_file():
                    warnings.append(f"untracked path is not a regular file: {path}")
                    continue
                facts.append(
                    ChangedFileFact(
                        file_path=path, change_kind="ADDED", old_path=None, new_path=path, old_sha=None,
                        new_sha=_blob(root, None, path, working_tree=True), lines_added=0, lines_deleted=0,
                        diff_hunk_refs=(), source_provenance=(),
                    )
                )

        diff_digest = canonical_sha256([item.to_dict() for item in facts])
        provenance = (f"git:repository:{repository.repository_id}", f"git:diff:{diff_digest}")
        facts = [ChangedFileFact(**{**item.to_dict(), "source_provenance": provenance}) for item in facts]

        symbols: list[ChangedSymbolFact] = []
        symbol_nodes: list[tuple[str, ast.AST]] = []
        for file_fact in facts:
            path = file_fact.new_path or file_fact.file_path
            if file_fact.change_kind == "DELETED" or not path.endswith(".py"):
                if path.endswith(".py") and file_fact.change_kind != "DELETED":
                    warnings.append(f"unsupported Python source state for {path}")
                continue
            source_path = root / path
            try:
                source = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"source read failed for {path}: {exc}")
                continue
            file_symbols, nodes, parse_warnings = _python_symbols(path, source, changed_lines.get(path, ()))
            warnings.extend(parse_warnings)
            old_signatures: dict[str, str] = {}
            if base_sha and file_fact.old_path:
                old_source = _try_git(root, ["show", f"{base_sha}:{file_fact.old_path}"])
                if old_source is not None:
                    old_signatures = _python_signature_map(old_source, file_fact.old_path)
            symbols.extend(
                ChangedSymbolFact(
                    symbol_id=item.symbol_id,
                    file_path=item.file_path,
                    symbol_kind=item.symbol_kind,
                    change_kind=item.change_kind,
                    old_signature=old_signatures.get(item.symbol_id),
                    new_signature=item.new_signature,
                    line_refs=item.line_refs,
                    source_provenance=provenance,
                )
                for item in file_symbols
            )
            symbol_nodes.extend(nodes)

        provider_ref = f"{provider_id}:{provider_version}:{input_digest}"
        edges = _python_edges(tuple(symbols), symbol_nodes, provider_ref, provenance)
        surfaces = _python_surfaces(tuple(symbols), symbol_nodes, provenance)
        if any(item.confidence < 0.8 for item in edges):
            warnings.append("one or more call-chain targets are unresolved")
        if any(not (item.new_path or "").endswith(".py") for item in facts):
            warnings.append("non-Python changed files have no symbol/call-chain resolution")

        resolved = set(requested)
        if "changed_symbols" in resolved and warnings:
            resolved.discard("changed_symbols")
        if "call_chain" in resolved and any(item.confidence < 0.8 for item in edges):
            resolved.discard("call_chain")
        if "impacted_surfaces" in resolved and not surfaces and facts:
            # No surface is evidence of no resolved surface, not an invented surface.
            resolved.discard("impacted_surfaces")
        if not set(requested).issubset(resolved):
            status = "PARTIAL"
        else:
            status = "COMPLETE"
        if not facts and repository.compare_mode == "WORKING_TREE" and repository.untracked_policy == "EXCLUDE":
            status = "COMPLETE"
        compare_identity = CompareIdentity(
            repository_id=repository.repository_id, compare_mode=repository.compare_mode,
            base_ref=repository.base_ref, base_sha=base_sha, head_ref=repository.head_ref, head_sha=head_sha,
            commit_range=repository.commit_range, working_tree_status_digest=status_digest,
            untracked_policy=repository.untracked_policy, diff_digest=diff_digest, policy_version=policy_version,
            provider_id=provider_id, provider_version=provider_version, code_graph_digest=None,
        )
        return CodeIntelligenceEnvelope(
            compare_identity=compare_identity, provider_id=provider_id, provider_version=provider_version,
            requested_capabilities=requested, resolved_capabilities=tuple(sorted(resolved)),
            code_intelligence_status=status, provider_input_digest=input_digest, code_graph_digest=None,
            changed_files=tuple(facts), changed_symbols=tuple(symbols), impact_edges=edges,
            impacted_surfaces=surfaces, warnings=tuple(sorted(set(warnings))), source_refs=provenance,
        )

    def _compare_args(self, root: Path, repository: RepositoryCompareRequest) -> tuple[list[str], str | None, str | None]:
        if repository.compare_mode in {"BASE_HEAD", "BRANCH"}:
            base = repository.base_sha or repository.base_ref
            head = repository.head_sha or repository.head_ref
            base_sha = _commit(root, base)
            head_sha = _commit(root, head)
            if not base_sha or not head_sha:
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "base/head refs could not be resolved")
            return [base_sha, head_sha], base_sha, head_sha
        if repository.compare_mode == "COMMIT_RANGE":
            if not repository.commit_range:
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "commit_range is required")
            parts = repository.commit_range.split("..")
            if len(parts) != 2 or not all(parts):
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "commit_range must be an explicit A..B range")
            base_sha, head_sha = _commit(root, parts[0]), _commit(root, parts[1])
            if not base_sha or not head_sha:
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "commit range refs could not be resolved")
            return [base_sha, head_sha], base_sha, head_sha
        base = repository.base_sha or repository.base_ref
        base_sha = _commit(root, base)
        head_sha = _commit(root, "HEAD")
        if not base_sha or not head_sha:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "working-tree base/HEAD could not be resolved")
        return [base_sha], base_sha, head_sha

    @staticmethod
    def _unavailable(
        repository: RepositoryCompareRequest,
        provider_id: str,
        provider_version: str,
        requested: tuple[str, ...],
        input_digest: str,
        policy_version: str,
        warning: str,
    ) -> CodeIntelligenceEnvelope:
        diff_digest = canonical_sha256({"repository": repository.to_dict(), "status": "UNAVAILABLE"})
        compare = CompareIdentity(
            repository_id=repository.repository_id, compare_mode=repository.compare_mode,
            base_ref=repository.base_ref, base_sha=repository.base_sha, head_ref=repository.head_ref, head_sha=repository.head_sha,
            commit_range=repository.commit_range, working_tree_status_digest=repository.working_tree_status_digest,
            untracked_policy=repository.untracked_policy, diff_digest=diff_digest, policy_version=policy_version,
            provider_id=provider_id, provider_version=provider_version,
        )
        return CodeIntelligenceEnvelope(
            compare_identity=compare, provider_id=provider_id, provider_version=provider_version,
            requested_capabilities=requested, resolved_capabilities=(), code_intelligence_status="UNAVAILABLE",
            provider_input_digest=input_digest, code_graph_digest=None, changed_files=(), changed_symbols=(),
            impact_edges=(), impacted_surfaces=(), warnings=(warning,), source_refs=(f"git:repository:{repository.repository_id}",),
        )


class MappingCodeIntelligenceProvider:
    """Deterministic provider boundary for replay-focused tests and approved adapters."""

    def __init__(self, envelope: CodeIntelligenceEnvelope | Mapping[str, Any]) -> None:
        self._envelope = envelope if isinstance(envelope, CodeIntelligenceEnvelope) else CodeIntelligenceEnvelope.from_dict(envelope)

    def collect(
        self,
        repository: RepositoryCompareRequest,
        code_intelligence: Mapping[str, Any],
        *,
        policy_version: str,
    ) -> CodeIntelligenceEnvelope:
        expected = {
            "provider_id": str(code_intelligence["provider_id"]),
            "provider_version": str(code_intelligence["provider_version"]),
            "provider_input_digest": str(code_intelligence["provider_input_digest"]),
        }
        actual = {
            "provider_id": self._envelope.provider_id,
            "provider_version": self._envelope.provider_version,
            "provider_input_digest": self._envelope.provider_input_digest,
        }
        if expected != actual:
            raise R32Error("R3_2_PROVIDER_IDENTITY_MISMATCH", "provider envelope does not match request")
        compare = self._envelope.compare_identity
        if compare.repository_id != repository.repository_id or compare.policy_version != policy_version:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "provider compare identity does not match request")
        return self._envelope
