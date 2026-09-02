from __future__ import annotations

import ast
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.r3_2.contracts import (
    ChangedFileFact,
    ChangedSymbolFact,
    CodeIntelligenceEnvelope,
    CompareIdentity,
    ImpactEdge,
    ImpactedSurface,
    RepositoryCompareRequest,
)

from .codegraph_provider import (
    CodeGraphContribution,
    CodeGraphProvider,
    CodeGraphProviderResolver,
    StructuralLineMapping,
)

_PROVIDER_ID = "g3.change-intelligence-broker"
_PROVIDER_VERSION = "2.0.0"
_REQUESTED = ("CHANGED_FILES", "CHANGED_SYMBOLS", "IMPACT_SURFACES", "LANGUAGE_AWARE")

_LANG = {
    ".py": "PYTHON",
    ".java": "JAVA",
    ".js": "JAVASCRIPT",
    ".jsx": "JAVASCRIPT",
    ".ts": "TYPESCRIPT",
    ".tsx": "TYPESCRIPT",
    ".vue": "VUE",
}
_CONFIG = {".yml", ".yaml", ".json", ".properties", ".toml", ".ini", ".xml", ".sql"}


@dataclass(frozen=True)
class GitChangeTruth:
    request: RepositoryCompareRequest
    name_status: str
    numstat: str
    diff: str
    changed_files: tuple[ChangedFileFact, ...]
    line_map: Mapping[str, tuple[int, ...]]
    texts: Mapping[str, str]
    change_kinds: Mapping[str, str]
    languages: Mapping[str, str | None]


class GitChangeTruthProvider:
    provider_id = "git"

    @staticmethod
    def _run(repo: Path, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and proc.returncode != 0:
            raise RuntimeError("G3_GIT_PROVIDER_FAILED", proc.stderr.strip() or "git command failed")
        return proc.stdout

    @classmethod
    def _resolved(cls, repo: Path, ref: str) -> str:
        return cls._run(repo, "rev-parse", ref).strip()

    @staticmethod
    def _status_kind(letter: str) -> str:
        return {
            "A": "ADDED",
            "M": "MODIFIED",
            "D": "DELETED",
            "R": "RENAMED",
            "C": "COPIED",
            "T": "TYPE_CHANGED",
        }.get(letter[:1], "MODIFIED")

    @staticmethod
    def _changed_lines(diff: str) -> dict[str, tuple[int, ...]]:
        current: str | None = None
        lines: dict[str, list[int]] = {}
        for raw in diff.splitlines():
            if raw.startswith("+++ b/"):
                current = raw[6:]
                lines.setdefault(current, [])
                continue
            if raw.startswith("@@") and current:
                match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
                if match:
                    start = int(match.group(1))
                    count = int(match.group(2) or 1)
                    lines[current].extend(range(start, start + count))
        return {key: tuple(sorted(set(value))) for key, value in lines.items()}

    def analyze(self, spec: Mapping[str, Any]) -> GitChangeTruth:
        repo = Path(str(spec["repository_path"])).resolve()
        if not (repo / ".git").exists() and not self._run(repo, "rev-parse", "--git-dir", check=False).strip():
            raise RuntimeError("G3_GIT_REPOSITORY_REQUIRED", str(repo))
        repository_id = str(spec.get("repository_id") or repo.name)
        base_ref = str(spec.get("base_ref") or "master")
        head_ref = str(spec.get("head_ref") or "HEAD")
        base_sha = self._resolved(repo, base_ref)
        head_sha = self._resolved(repo, head_ref)
        request = RepositoryCompareRequest(
            repository_id=repository_id,
            compare_mode="BASE_HEAD",
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=head_sha,
            repository_path=str(repo),
        )
        name_status = self._run(repo, "diff", "--name-status", f"{base_sha}..{head_sha}")
        numstat = self._run(repo, "diff", "--numstat", f"{base_sha}..{head_sha}")
        diff = self._run(repo, "diff", "--unified=0", f"{base_sha}..{head_sha}")
        line_map = self._changed_lines(diff)
        nums: dict[str, tuple[int, int]] = {}
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    nums[parts[-1]] = (
                        int(parts[0]) if parts[0].isdigit() else 0,
                        int(parts[1]) if parts[1].isdigit() else 0,
                    )
                except ValueError:
                    nums[parts[-1]] = (0, 0)
        files: list[ChangedFileFact] = []
        texts: dict[str, str] = {}
        change_kinds: dict[str, str] = {}
        languages: dict[str, str | None] = {}
        for raw in name_status.splitlines():
            if not raw.strip():
                continue
            parts = raw.split("\t")
            status = parts[0]
            path = parts[-1]
            old_path = parts[1] if status.startswith(("R", "C")) and len(parts) >= 3 else None
            kind = self._status_kind(status)
            added, deleted = nums.get(path, (0, 0))
            changed = line_map.get(path, ())
            files.append(
                ChangedFileFact(
                    path,
                    kind,
                    old_path,
                    path if kind != "DELETED" else None,
                    None,
                    None,
                    added,
                    deleted,
                    tuple(f"{path}:L{x}" for x in changed),
                    (f"git:{base_sha}..{head_sha}",),
                )
            )
            texts[path] = "" if kind == "DELETED" else self._run(repo, "show", f"{head_sha}:{path}", check=False)
            change_kinds[path] = kind
            languages[path] = _LANG.get(Path(path).suffix.lower())
        return GitChangeTruth(
            request,
            name_status,
            numstat,
            diff,
            tuple(files),
            line_map,
            texts,
            change_kinds,
            languages,
        )


def _symbols_python(text: str, path: str, changed: tuple[int, ...], kind: str) -> list[ChangedSymbolFact]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    result: list[ChangedSymbolFact] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = int(getattr(node, "lineno", 1))
            end = int(getattr(node, "end_lineno", start))
            refs = tuple(v for v in changed if start <= v <= end)
            if refs:
                skind = "CLASS" if isinstance(node, ast.ClassDef) else "FUNCTION"
                result.append(
                    ChangedSymbolFact(
                        f"{path}:{node.name}",
                        path,
                        skind,
                        kind,
                        None,
                        node.name,
                        refs,
                        (f"git:{path}", "language:python-ast"),
                    )
                )
    return result


def _symbols_regex(text: str, path: str, changed: tuple[int, ...], kind: str, lang: str) -> list[ChangedSymbolFact]:
    patterns = {
        "JAVA": re.compile(
            r"\b(class|interface|enum|record)\s+(\w+)|(?:public|protected|private|static|final|synchronized|abstract|native|\s)+[\w<>\[\], ?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:throws [^{]+)?\{"
        ),
        "JAVASCRIPT": re.compile(
            r"\bclass\s+(\w+)|\bfunction\s+(\w+)\s*\(|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>"
        ),
        "TYPESCRIPT": re.compile(
            r"\b(?:class|interface|type|enum)\s+(\w+)|\bfunction\s+(\w+)\s*\(|\b(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>"
        ),
        "VUE": re.compile(
            r"\b(?:defineComponent|defineProps|defineEmits)\b|\bfunction\s+(\w+)\s*\(|\b(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>"
        ),
    }
    pattern = patterns[lang]
    result: list[ChangedSymbolFact] = []
    for idx, line in enumerate(text.splitlines(), 1):
        if idx not in changed:
            continue
        match = pattern.search(line)
        if not match:
            continue
        groups = [group for group in match.groups() if group] if match.groups() else []
        name = groups[-1] if groups else f"line-{idx}"
        result.append(
            ChangedSymbolFact(
                f"{path}:{name}",
                path,
                "SYMBOL",
                kind,
                None,
                name,
                (idx,),
                (f"git:{path}", f"language:{lang.lower()}-regex"),
            )
        )
    return result


def _vue_script_lines(text: str) -> set[int]:
    active = False
    result: set[int] = set()
    for idx, raw in enumerate(text.splitlines(), 1):
        low = raw.lower()
        if "<script" in low:
            active = True
            continue
        if "</script" in low:
            active = False
            continue
        if active:
            result.add(idx)
    return result


def _relevant_executable_lines(text: str, changed: tuple[int, ...], lang: str | None) -> tuple[int, ...]:
    if not lang:
        return ()
    lines = text.splitlines()
    vue_script = _vue_script_lines(text) if lang == "VUE" else None
    result: list[int] = []
    for line_no in changed:
        if line_no < 1 or line_no > len(lines):
            continue
        if vue_script is not None and line_no not in vue_script:
            continue
        stripped = lines[line_no - 1].strip()
        if not stripped:
            continue
        if stripped.startswith(("//", "/*", "*", "*/", "#")):
            continue
        if stripped in {"{", "}", "};", ");", "]", "];"}:
            continue
        result.append(line_no)
    return tuple(result)


def _surfaces(path: str, text: str) -> list[ImpactedSurface]:
    low = path.lower()
    result: list[ImpactedSurface] = []

    def add(kind: str, stable: str, relation: str, confidence: float, evidence: str) -> None:
        item = ImpactedSurface(kind, stable, relation, confidence, (evidence,))
        if all((value.surface_kind, value.stable_surface_id) != (item.surface_kind, item.stable_surface_id) for value in result):
            result.append(item)

    if path.endswith(".vue") or "/pages/" in low or "/views/" in low or "/components/" in low:
        add("PAGE", path, "CHANGED_PAGE_SURFACE", 0.95, f"file:{path}")
    if re.search(r"@(Get|Post|Put|Delete|Patch|Request)Mapping|@(app|router)\.(get|post|put|delete|patch)|\b(fetch|axios)\s*\(?", text, re.I):
        add("API", path, "API_DECLARATION_OR_CALL", 0.85, f"file:{path}")
    if path.endswith(".sql") or re.search(r"\b(select|insert|update|delete)\s+.+\b(from|into|set)\b|@Entity|Repository\b", text, re.I):
        add("DB", path, "DATA_RELATION", 0.8, f"file:{path}")
    if any(token in low for token in ("service", "controller", "gateway", "client", "adapter")):
        add("SERVICE", path, "SERVICE_CHANGE", 0.75, f"file:{path}")
    if any(token in low for token in ("config", "application.yml", "properties", "feature", "route")):
        add("SYSTEM", path, "CONFIG_OR_SYSTEM_CHANGE", 0.7, f"file:{path}")
    return result


class LanguageStructuralProvider:
    """AST/structural fallback. Regex is intentionally last-resort/PARTIAL."""

    def analyze(
        self,
        git_truth: GitChangeTruth,
        codegraph_mappings: Sequence[StructuralLineMapping],
    ) -> tuple[list[ChangedSymbolFact], dict[str, str], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        symbols: list[ChangedSymbolFact] = []
        caps: dict[str, str] = {}
        mapping_rows: list[dict[str, Any]] = []
        obligations: list[dict[str, Any]] = []
        warnings: list[str] = []
        graph_by_line = {(item.file_path, item.line_number): item for item in codegraph_mappings}
        graph_symbol_lines: dict[tuple[str, str], list[int]] = {}
        graph_symbol_meta: dict[tuple[str, str], StructuralLineMapping] = {}
        for item in codegraph_mappings:
            key = (item.file_path, item.symbol_id)
            graph_symbol_lines.setdefault(key, []).append(item.line_number)
            graph_symbol_meta[key] = item
        for key, line_refs in graph_symbol_lines.items():
            item = graph_symbol_meta[key]
            symbols.append(
                ChangedSymbolFact(
                    item.symbol_id,
                    item.file_path,
                    item.symbol_kind,
                    git_truth.change_kinds[item.file_path],
                    None,
                    item.symbol_name,
                    tuple(sorted(set(line_refs))),
                    item.source_provenance,
                )
            )

        for file_fact in git_truth.changed_files:
            path = file_fact.file_path
            lang = git_truth.languages.get(path)
            text = git_truth.texts.get(path, "")
            changed = git_truth.line_map.get(path, ())
            suffix = Path(path).suffix.lower()
            if not lang:
                if suffix in _CONFIG:
                    caps[f"CONFIG:{suffix or 'none'}"] = "AVAILABLE"
                else:
                    caps[f"UNSUPPORTED:{suffix or '<none>'}"] = "UNAVAILABLE"
                    warnings.append(f"UNSUPPORTED_LANGUAGE:{path}")
                continue
            relevant = _relevant_executable_lines(text, changed, lang)
            native_symbols: list[ChangedSymbolFact]
            if lang == "PYTHON":
                native_symbols = _symbols_python(text, path, changed, git_truth.change_kinds[path])
                caps[lang] = "AVAILABLE"
            else:
                native_symbols = _symbols_regex(text, path, changed, git_truth.change_kinds[path], lang)
                # Regex is last-resort and can never self-certify complete structural truth.
                caps[lang] = "PARTIAL" if relevant else "AVAILABLE"
            symbols.extend(native_symbols)
            native_by_line: dict[int, ChangedSymbolFact] = {}
            for symbol in native_symbols:
                for line_no in symbol.line_refs:
                    native_by_line.setdefault(line_no, symbol)
            for line_no in relevant:
                graph_mapping = graph_by_line.get((path, line_no))
                native = native_by_line.get(line_no)
                if graph_mapping is not None:
                    mapping_rows.append({
                        "file_path": path,
                        "line_ref": f"{path}:L{line_no}",
                        "line_number": line_no,
                        "status": "MAPPED_TO_SYMBOL",
                        "symbol_id": graph_mapping.symbol_id,
                        "provider": "CODEGRAPH",
                        "confidence": graph_mapping.confidence,
                    })
                elif native is not None:
                    provider = "PYTHON_AST" if lang == "PYTHON" else "LANGUAGE_REGEX_LAST_RESORT"
                    mapping_rows.append({
                        "file_path": path,
                        "line_ref": f"{path}:L{line_no}",
                        "line_number": line_no,
                        "status": "MAPPED_TO_SYMBOL",
                        "symbol_id": native.symbol_id,
                        "provider": provider,
                        "confidence": 0.98 if provider == "PYTHON_AST" else 0.55,
                    })
                else:
                    ref = f"{path}:L{line_no}"
                    mapping_rows.append({
                        "file_path": path,
                        "line_ref": ref,
                        "line_number": line_no,
                        "status": "UNMAPPED",
                        "symbol_id": None,
                        "provider": None,
                        "confidence": 0.0,
                    })
                    obligations.append({
                        "obligation_kind": "MISSING_SYMBOL_MAPPING",
                        "status": "OPEN",
                        "file_path": path,
                        "changed_line_refs": [ref],
                        "language": lang,
                        "risk_semantics": "CHANGED_EXECUTABLE_LINE_REMAINS_COVERAGE_AND_RISK_OBLIGATION",
                        "resolution_requirement": "RESOLVE_ENCLOSING_SYMBOL_OR_RETAIN_EXACT_LINE_LEVEL_TEST_OBLIGATION",
                    })
                    warnings.append(f"MISSING_SYMBOL_MAPPING:{ref}")
        # De-duplicate symbols from overlapping graph/AST coverage.
        merged: dict[tuple[str, str], ChangedSymbolFact] = {}
        for item in symbols:
            key = (item.file_path, item.symbol_id)
            previous = merged.get(key)
            if previous is None:
                merged[key] = item
            else:
                merged[key] = ChangedSymbolFact(
                    previous.symbol_id,
                    previous.file_path,
                    previous.symbol_kind,
                    previous.change_kind,
                    previous.old_signature,
                    previous.new_signature,
                    tuple(sorted(set(previous.line_refs + item.line_refs))),
                    tuple(dict.fromkeys(previous.source_provenance + item.source_provenance)),
                )
        return list(merged.values()), caps, mapping_rows, obligations, warnings


def _ripgrep_reference_edges(repo: Path, symbols: Sequence[ChangedSymbolFact], provider_available: bool) -> list[ImpactEdge]:
    if not provider_available:
        return []
    edges: list[ImpactEdge] = []
    seen: set[tuple[str, str]] = set()
    for symbol in symbols[:100]:
        name = str(symbol.new_signature or symbol.symbol_id.rsplit(":", 1)[-1] or "").strip()
        if len(name) < 3 or name.startswith("line-"):
            continue
        proc = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--fixed-strings", name, str(repo)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode not in {0, 1}:
            continue
        for raw in proc.stdout.splitlines()[:100]:
            parts = raw.split(":", 2)
            if len(parts) < 3:
                continue
            raw_path, raw_line, _ = parts
            try:
                line_no = int(raw_line)
            except ValueError:
                continue
            try:
                rel = Path(raw_path).resolve().relative_to(repo).as_posix()
            except (ValueError, OSError):
                rel = Path(raw_path).name
            target = f"{rel}:L{line_no}"
            key = (symbol.symbol_id, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                ImpactEdge(
                    symbol.symbol_id,
                    target,
                    "REFERENCE",
                    "OUTBOUND",
                    1,
                    0.70,
                    "ripgrep",
                    (f"rg:{name}", f"file:{rel}:L{line_no}"),
                )
            )
    return edges


class ChangeIntelligenceBroker:
    """Provider-neutral composition over mandatory Git change truth."""

    def __init__(
        self,
        *,
        git_provider: GitChangeTruthProvider | None = None,
        codegraph_provider: CodeGraphProvider | None = None,
        language_provider: LanguageStructuralProvider | None = None,
    ) -> None:
        self.git_provider = git_provider or GitChangeTruthProvider()
        self.codegraph_provider = codegraph_provider
        self.language_provider = language_provider or LanguageStructuralProvider()

    def analyze(self, spec: Mapping[str, Any]) -> tuple[RepositoryCompareRequest, CodeIntelligenceEnvelope, dict[str, Any]]:
        git_truth = self.git_provider.analyze(spec)
        repo = Path(git_truth.request.repository_path).resolve()
        relevant_pairs: list[tuple[str, int]] = []
        for file_fact in git_truth.changed_files:
            lang = git_truth.languages.get(file_fact.file_path)
            relevant = _relevant_executable_lines(
                git_truth.texts.get(file_fact.file_path, ""),
                git_truth.line_map.get(file_fact.file_path, ()),
                lang,
            )
            relevant_pairs.extend((file_fact.file_path, line_no) for line_no in relevant)

        codegraph_provider = self.codegraph_provider or CodeGraphProviderResolver.resolve(spec)
        codegraph: CodeGraphContribution = codegraph_provider.analyze(repo, git_truth.request, tuple(relevant_pairs))
        symbols, language_caps, line_mapping, obligations, language_warnings = self.language_provider.analyze(git_truth, codegraph.mappings)
        surfaces: list[ImpactedSurface] = []
        for file_fact in git_truth.changed_files:
            surfaces.extend(_surfaces(file_fact.file_path, git_truth.texts.get(file_fact.file_path, "")))

        rg = shutil.which("rg")
        impact_edges = list(codegraph.impact_edges)
        impact_edges.extend(_ripgrep_reference_edges(repo, symbols, bool(rg)))
        provider_caps = {
            "GIT": "AVAILABLE",
            "RIPGREP": "AVAILABLE" if rg else "UNAVAILABLE",
            "CODEGRAPH": codegraph.health.status,
            "API_SCHEMA_CONFIG": "AVAILABLE",
            **language_caps,
        }
        warnings = list(codegraph.warnings) + language_warnings
        if codegraph.health.status == "UNAVAILABLE":
            warnings.append("CODEGRAPH_UNAVAILABLE")
        elif codegraph.health.status == "BLOCKED":
            warnings.append("CODEGRAPH_BLOCKED")
        elif codegraph.health.status == "PARTIAL":
            warnings.append("CODEGRAPH_PARTIAL")
        if not rg:
            warnings.append("RIPGREP_UNAVAILABLE")

        regex_only = any(row.get("provider") == "LANGUAGE_REGEX_LAST_RESORT" for row in line_mapping)
        unsupported = any(key.startswith("UNSUPPORTED:") and value == "UNAVAILABLE" for key, value in provider_caps.items())
        mapping_complete = not obligations
        structural_complete = mapping_complete and not regex_only and not unsupported
        if not git_truth.changed_files:
            status = "COMPLETE"
            structural_complete = True
        elif structural_complete:
            status = "COMPLETE"
        else:
            status = "PARTIAL"

        diff_digest = canonical_sha256({
            "name_status": git_truth.name_status,
            "numstat": git_truth.numstat,
            "diff": git_truth.diff,
        })
        provider_health = {
            "GIT": {"provider_id": "git", "status": "AVAILABLE", "authority": "CHANGED_FILE_LINE_TRUTH"},
            "CODEGRAPH": codegraph.health.to_dict(),
            "RIPGREP": {"provider_id": "ripgrep", "status": provider_caps["RIPGREP"], "authority": "REFERENCE_ENRICHMENT_ONLY"},
            "LANGUAGE": {"provider_id": "language-structural-fallback", "status": "AVAILABLE" if structural_complete else "PARTIAL", "capabilities": dict(language_caps)},
            "API_SCHEMA_CONFIG": {"provider_id": "api-schema-config", "status": "AVAILABLE", "authority": "SURFACE_ENRICHMENT_ONLY"},
        }
        input_digest = canonical_sha256({
            "repository": git_truth.request.to_dict(),
            "provider_health": provider_health,
            "line_mapping": line_mapping,
        })
        compare = CompareIdentity(
            git_truth.request.repository_id,
            "BASE_HEAD",
            git_truth.request.base_ref,
            git_truth.request.base_sha,
            git_truth.request.head_ref,
            git_truth.request.head_sha,
            None,
            None,
            "EXCLUDE",
            diff_digest,
            "g3.change-policy.v1",
            _PROVIDER_ID,
            _PROVIDER_VERSION,
            None,
        )
        resolved = tuple(cap for cap in _REQUESTED if cap != "LANGUAGE_AWARE" or structural_complete)
        source_refs = [f"git:{git_truth.request.repository_id}:{git_truth.request.base_sha}..{git_truth.request.head_sha}"]
        source_refs.extend(codegraph.source_refs)
        envelope = CodeIntelligenceEnvelope(
            compare,
            _PROVIDER_ID,
            _PROVIDER_VERSION,
            _REQUESTED,
            resolved,
            status,
            input_digest,
            codegraph.graph_digest,
            git_truth.changed_files,
            tuple(symbols),
            tuple(impact_edges),
            tuple(surfaces),
            tuple(dict.fromkeys(warnings)),
            tuple(dict.fromkeys(source_refs)),
        )
        metadata = {
            "repository_id": git_truth.request.repository_id,
            "repository_path": str(repo),
            "base_ref": git_truth.request.base_ref,
            "base_sha": git_truth.request.base_sha,
            "head_ref": git_truth.request.head_ref,
            "head_sha": git_truth.request.head_sha,
            "provider_capabilities": provider_caps,
            "provider_health": provider_health,
            "provider_provenance": {
                "git_diff_digest": diff_digest,
                "codegraph_graph_digest": codegraph.graph_digest,
                "codegraph_source_refs": list(codegraph.source_refs),
                "broker_input_digest": input_digest,
            },
            "line_mapping": line_mapping,
            "mapping_obligations": obligations,
            "impact_edge_count": len(impact_edges),
            "status": status,
        }
        return git_truth.request, envelope, metadata


def analyze_repository(
    spec: Mapping[str, Any],
    *,
    broker: ChangeIntelligenceBroker | None = None,
) -> tuple[RepositoryCompareRequest, CodeIntelligenceEnvelope, dict[str, Any]]:
    return (broker or ChangeIntelligenceBroker()).analyze(spec)
