from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.r3_2.contracts import (
    ChangedFileFact, ChangedSymbolFact, CodeIntelligenceEnvelope, CompareIdentity,
    ImpactEdge, ImpactedSurface, RepositoryCompareRequest,
)

_PROVIDER_ID = "g3.multi-language-change-intelligence"
_PROVIDER_VERSION = "1.0.0"
_REQUESTED = ("CHANGED_FILES", "CHANGED_SYMBOLS", "IMPACT_SURFACES", "LANGUAGE_AWARE")

_LANG = {
    ".py": "PYTHON", ".java": "JAVA", ".js": "JAVASCRIPT", ".jsx": "JAVASCRIPT",
    ".ts": "TYPESCRIPT", ".tsx": "TYPESCRIPT", ".vue": "VUE",
}
_CONFIG = {".yml", ".yaml", ".json", ".properties", ".toml", ".ini", ".xml", ".sql"}


def _run(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError("G3_GIT_PROVIDER_FAILED", proc.stderr.strip() or "git command failed")
    return proc.stdout


def _resolved(repo: Path, ref: str) -> str:
    return _run(repo, "rev-parse", ref).strip()


def _status_kind(letter: str) -> str:
    return {"A": "ADDED", "M": "MODIFIED", "D": "DELETED", "R": "RENAMED", "C": "COPIED", "T": "TYPE_CHANGED"}.get(letter[:1], "MODIFIED")


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
                start = int(match.group(1)); count = int(match.group(2) or 1)
                lines[current].extend(range(start, start + count))
    return {key: tuple(sorted(set(value))) for key, value in lines.items()}


def _symbols_python(text: str, path: str, changed: tuple[int, ...], kind: str) -> list[ChangedSymbolFact]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    result: list[ChangedSymbolFact] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = int(getattr(node, "lineno", 1)); end = int(getattr(node, "end_lineno", start))
            refs = tuple(v for v in changed if start <= v <= end)
            if refs:
                skind = "CLASS" if isinstance(node, ast.ClassDef) else "FUNCTION"
                result.append(ChangedSymbolFact(f"{path}:{node.name}", path, skind, kind, None, node.name, refs, (f"git:{path}", "language:python")))
    return result


def _symbols_regex(text: str, path: str, changed: tuple[int, ...], kind: str, lang: str) -> list[ChangedSymbolFact]:
    patterns = {
        "JAVA": re.compile(r"\b(class|interface|enum|record)\s+(\w+)|(?:public|protected|private|static|final|synchronized|abstract|native|\s)+[\w<>\[\], ?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:throws [^{]+)?\{"),
        "JAVASCRIPT": re.compile(r"\bclass\s+(\w+)|\bfunction\s+(\w+)\s*\(|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>"),
        "TYPESCRIPT": re.compile(r"\b(?:class|interface|type|enum)\s+(\w+)|\bfunction\s+(\w+)\s*\(|\b(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>"),
        "VUE": re.compile(r"\b(?:defineComponent|defineProps|defineEmits)\b|\bfunction\s+(\w+)\s*\(|\b(?:const|let)\s+(\w+)\s*="),
    }
    pattern = patterns[lang]
    result: list[ChangedSymbolFact] = []
    for idx, line in enumerate(text.splitlines(), 1):
        if idx not in changed:
            continue
        m = pattern.search(line)
        if not m:
            continue
        groups = [g for g in m.groups() if g] if m.groups() else []
        name = groups[-1] if groups else f"line-{idx}"
        result.append(ChangedSymbolFact(f"{path}:{name}", path, "SYMBOL", kind, None, name, (idx,), (f"git:{path}", f"language:{lang.lower()}")))
    return result


def _surfaces(path: str, text: str) -> list[ImpactedSurface]:
    low = path.lower(); result: list[ImpactedSurface] = []
    def add(kind: str, stable: str, relation: str, confidence: float, evidence: str) -> None:
        item = ImpactedSurface(kind, stable, relation, confidence, (evidence,))
        if all((x.surface_kind, x.stable_surface_id) != (item.surface_kind, item.stable_surface_id) for x in result): result.append(item)
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



def _ripgrep_reference_edges(repo: Path, symbols: list[ChangedSymbolFact], provider_available: bool) -> list[ImpactEdge]:
    """Best-effort reference evidence; absence/failure is never upgraded into guessed impact."""
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
            capture_output=True, text=True, encoding="utf-8", errors="replace",
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
            edges.append(ImpactEdge(symbol.symbol_id, target, "REFERENCE", "OUTBOUND", 1, 0.70, "ripgrep", (f"rg:{name}", f"file:{rel}:L{line_no}")))
    return edges

def analyze_repository(spec: Mapping[str, Any]) -> tuple[RepositoryCompareRequest, CodeIntelligenceEnvelope, dict[str, Any]]:
    repo = Path(str(spec["repository_path"])).resolve()
    if not (repo / ".git").exists() and not _run(repo, "rev-parse", "--git-dir", check=False).strip():
        raise RuntimeError("G3_GIT_REPOSITORY_REQUIRED", str(repo))
    repository_id = str(spec.get("repository_id") or repo.name)
    base_ref = str(spec.get("base_ref") or "master")
    head_ref = str(spec.get("head_ref") or "HEAD")
    base_sha = _resolved(repo, base_ref); head_sha = _resolved(repo, head_ref)
    request = RepositoryCompareRequest(repository_id=repository_id, compare_mode="BASE_HEAD", base_ref=base_ref, base_sha=base_sha, head_ref=head_ref, head_sha=head_sha, repository_path=str(repo))
    name_status = _run(repo, "diff", "--name-status", f"{base_sha}..{head_sha}")
    numstat = _run(repo, "diff", "--numstat", f"{base_sha}..{head_sha}")
    diff = _run(repo, "diff", "--unified=0", f"{base_sha}..{head_sha}")
    line_map = _changed_lines(diff)
    nums: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try: nums[parts[-1]] = (int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if parts[1].isdigit() else 0)
            except ValueError: nums[parts[-1]] = (0, 0)
    files: list[ChangedFileFact] = []; symbols: list[ChangedSymbolFact] = []; surfaces: list[ImpactedSurface] = []
    warnings: list[str] = []; language_status: dict[str, str] = {}
    for raw in name_status.splitlines():
        if not raw.strip(): continue
        parts = raw.split("\t"); status = parts[0]; path = parts[-1]; old_path = parts[1] if status.startswith(("R", "C")) and len(parts) >= 3 else None
        kind = _status_kind(status); added, deleted = nums.get(path, (0, 0)); changed = line_map.get(path, ())
        files.append(ChangedFileFact(path, kind, old_path, path if kind != "DELETED" else None, None, None, added, deleted, tuple(f"{path}:L{x}" for x in changed), (f"git:{base_sha}..{head_sha}",)))
        suffix = Path(path).suffix.lower(); lang = _LANG.get(suffix)
        if kind == "DELETED": text = ""
        else: text = _run(repo, "show", f"{head_sha}:{path}", check=False)
        if lang:
            if lang == "PYTHON":
                mapped = _symbols_python(text, path, changed, kind)
                language_status[lang] = "AVAILABLE"
            else:
                mapped = _symbols_regex(text, path, changed, kind, lang)
                # Regex providers can recognize declaration-line edits but cannot
                # reliably recover an enclosing symbol for arbitrary body-only edits.
                # Never claim COMPLETE language-aware symbol truth when changed lines
                # exist but no symbol can be mapped. Preserve the gap explicitly.
                if changed and not mapped:
                    language_status[lang] = "PARTIAL"
                    warnings.append(f"MISSING_SYMBOL_MAPPING:{path}")
                else:
                    language_status[lang] = "AVAILABLE"
            symbols.extend(mapped)
        elif suffix in _CONFIG:
            language_status[f"CONFIG:{suffix or 'none'}"] = "AVAILABLE"
        else:
            language_status[f"UNSUPPORTED:{suffix or '<none>'}"] = "UNAVAILABLE"
            warnings.append(f"UNSUPPORTED_LANGUAGE:{path}")
        surfaces.extend(_surfaces(path, text))
    rg = shutil.which("rg")
    impact_edges = _ripgrep_reference_edges(repo, symbols, bool(rg))
    # A binary being present is not enough to claim a canonical CodeGraph provider.
    # Until an adapter/profile is field-bound, capability remains explicit UNAVAILABLE.
    provider_caps = {
        "GIT": "AVAILABLE", "RIPGREP": "AVAILABLE" if rg else "UNAVAILABLE",
        "CODEGRAPH": "UNAVAILABLE",
        **language_status,
    }
    if not files:
        status = "COMPLETE"
    elif any(value == "UNAVAILABLE" for key, value in provider_caps.items() if key.startswith("UNSUPPORTED:")):
        status = "PARTIAL"
    elif any(value == "PARTIAL" for value in provider_caps.values()):
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    if provider_caps["CODEGRAPH"] == "UNAVAILABLE": warnings.append("CODEGRAPH_UNAVAILABLE")
    if provider_caps["RIPGREP"] == "UNAVAILABLE": warnings.append("RIPGREP_UNAVAILABLE")
    diff_digest = canonical_sha256({"name_status": name_status, "numstat": numstat, "diff": diff})
    input_digest = canonical_sha256({"repository": request.to_dict(), "provider_caps": provider_caps})
    compare = CompareIdentity(repository_id, "BASE_HEAD", base_ref, base_sha, head_ref, head_sha, None, None, "EXCLUDE", diff_digest, "g3.change-policy.v1", _PROVIDER_ID, _PROVIDER_VERSION, None)
    resolved = tuple(cap for cap in _REQUESTED if cap != "LANGUAGE_AWARE" or status == "COMPLETE")
    envelope = CodeIntelligenceEnvelope(compare, _PROVIDER_ID, _PROVIDER_VERSION, _REQUESTED, resolved, status, input_digest, None, tuple(files), tuple(symbols), tuple(impact_edges), tuple(surfaces), tuple(dict.fromkeys(warnings)), (f"git:{repository_id}:{base_sha}..{head_sha}",))
    metadata = {"repository_id": repository_id, "repository_path": str(repo), "base_ref": base_ref, "base_sha": base_sha, "head_ref": head_ref, "head_sha": head_sha, "provider_capabilities": provider_caps, "impact_edge_count": len(impact_edges), "status": status}
    return request, envelope, metadata
