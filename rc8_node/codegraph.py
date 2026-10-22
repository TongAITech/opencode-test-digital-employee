"""RC8 CodeGraph reality adapter.

Git is the change/snapshot authority. CodeGraph is structural enrichment and is
accepted only when real read-only graph tools execute against the same source
snapshot that is later published as evidence.

The adapter intentionally speaks the existing RC7/CodeGraph graph-only CLI
contract instead of inventing a second graph engine:

  codegraph --graph-only --workspace <repo> --run-tool <tool> --tool-args <json>

Python 3.8 compatible for bank execution nodes.
"""
from __future__ import annotations

import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class CodeGraphAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitSnapshot:
    head_revision: str
    dirty: bool
    status_sha256: str
    content_sha256: str
    snapshot_id: str


@dataclass(frozen=True)
class CodeGraphQueryPoint:
    file_path: str
    line_number: int
    source: str


@dataclass(frozen=True)
class CodeGraphExecutionResult:
    state: str
    classification: str
    project_dir: str
    base_ref: str
    head_ref: str
    snapshot_before: GitSnapshot
    snapshot_after: GitSnapshot
    changed_java_files: Tuple[str, ...]
    query_points: Tuple[CodeGraphQueryPoint, ...]
    tool_calls: Tuple[Dict[str, Any], ...]
    graph_digest: str
    evidence_path: str
    started_at: int
    finished_at: int


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _decode(raw: bytes) -> Tuple[str, str]:
    if not raw:
        return "", "empty"
    candidates = ["utf-8", "gb18030"]
    preferred = locale.getpreferredencoding(False)
    if preferred:
        candidates.append(preferred)
    seen = set()
    for encoding in candidates:
        lowered = encoding.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _run_bytes(command: Sequence[str], *, cwd: Path, timeout_seconds: int) -> Tuple[int, str, str, str, str]:
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CodeGraphAdapterError("COMMAND_NOT_FOUND:%s" % command[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise CodeGraphAdapterError("COMMAND_TIMEOUT:%s" % command[0]) from exc
    stdout, stdout_encoding = _decode(proc.stdout or b"")
    stderr, stderr_encoding = _decode(proc.stderr or b"")
    return proc.returncode, stdout, stderr, stdout_encoding, stderr_encoding


def _git(repo: Path, args: Sequence[str], *, timeout_seconds: int = 60) -> str:
    code, stdout, stderr, _, _ = _run_bytes(["git"] + list(args), cwd=repo, timeout_seconds=timeout_seconds)
    if code != 0:
        raise CodeGraphAdapterError("GIT_COMMAND_FAILED:%s:%s" % (" ".join(args), stderr.strip()[:500]))
    return stdout


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _dirty_untracked_java(repo: Path, status: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        raw_path = raw_path.strip('"').replace("\\", "/")
        if code == "??" and raw_path.endswith(".java"):
            path = repo / raw_path
            if path.is_file():
                rows.append((raw_path, _sha256_bytes(path.read_bytes())))
    return rows


def capture_git_snapshot(repo_path: str) -> GitSnapshot:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise CodeGraphAdapterError("CODEGRAPH_REPO_NOT_FOUND:%s" % repo)
    head = _git(repo, ["rev-parse", "HEAD"]).strip()
    if not head:
        raise CodeGraphAdapterError("CODEGRAPH_GIT_HEAD_EMPTY")
    status = _git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    diff = _git(repo, ["diff", "--binary", "HEAD", "--"])
    untracked = _dirty_untracked_java(repo, status)
    status_sha = _sha256_bytes(status.encode("utf-8"))
    content_payload = {
        "tracked_diff_sha256": _sha256_bytes(diff.encode("utf-8")),
        "untracked_java": untracked,
    }
    content_sha = _canonical_sha256(content_payload)
    snapshot_id = _canonical_sha256(
        {
            "head_revision": head,
            "status_sha256": status_sha,
            "content_sha256": content_sha,
        }
    )
    return GitSnapshot(head, bool(status.strip()), status_sha, content_sha, snapshot_id)


def _committed_changed_points(repo: Path, base_ref: str, head_ref: str) -> Tuple[List[str], List[CodeGraphQueryPoint]]:
    if not base_ref or not head_ref:
        return [], []
    diff = _git(repo, ["diff", "--unified=0", base_ref, head_ref, "--", "*.java"], timeout_seconds=120)
    current_file: Optional[str] = None
    files: List[str] = []
    points: List[CodeGraphQueryPoint] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].replace("\\", "/")
            if current_file not in files:
                files.append(current_file)
            continue
        match = _HUNK.match(line)
        if match and current_file:
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            if count > 0:
                points.append(CodeGraphQueryPoint(current_file, max(1, start), "git-diff"))
    return files, points


def _working_tree_java_files(repo: Path) -> List[str]:
    status = _git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    files: List[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        raw_path = raw_path.strip('"').replace("\\", "/")
        if raw_path.endswith(".java") and (repo / raw_path).is_file() and raw_path not in files:
            files.append(raw_path)
    return files


def discover_java_query_points(
    repo_path: str,
    *,
    base_ref: str,
    head_ref: str,
    target_file: Optional[str] = None,
    target_line: Optional[int] = None,
    max_points: int = 3,
) -> Tuple[Tuple[str, ...], Tuple[CodeGraphQueryPoint, ...]]:
    repo = Path(repo_path).resolve()
    if max_points < 1:
        raise CodeGraphAdapterError("CODEGRAPH_MAX_POINTS_INVALID")
    files, points = _committed_changed_points(repo, base_ref, head_ref)
    for path in _working_tree_java_files(repo):
        if path not in files:
            files.append(path)
        if not any(point.file_path == path for point in points):
            points.append(CodeGraphQueryPoint(path, 1, "working-tree"))
    if target_file:
        normalized = target_file.replace("\\", "/").lstrip("/")
        if not (repo / normalized).is_file():
            raise CodeGraphAdapterError("CODEGRAPH_TARGET_FILE_NOT_FOUND:%s" % normalized)
        if normalized not in files:
            files.append(normalized)
        points.insert(0, CodeGraphQueryPoint(normalized, max(1, int(target_line or 1)), "explicit-target"))
    unique: List[CodeGraphQueryPoint] = []
    seen = set()
    for point in points:
        key = (point.file_path, point.line_number)
        if key in seen:
            continue
        seen.add(key)
        unique.append(point)
    if not unique:
        raise CodeGraphAdapterError("CODEGRAPH_JAVA_CHANGE_OR_TARGET_REQUIRED")
    return tuple(files), tuple(unique[:max_points])


def _decode_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return _decode_jsonish(json.loads(text))
        except (ValueError, TypeError):
            return value
    if isinstance(value, Mapping):
        result = {str(key): _decode_jsonish(item) for key, item in value.items()}
        content = result.get("content")
        if isinstance(content, list):
            decoded: List[Any] = []
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    decoded.append(_decode_jsonish(item.get("text")))
                else:
                    decoded.append(_decode_jsonish(item))
            result["content"] = decoded
        return result
    if isinstance(value, list):
        return [_decode_jsonish(item) for item in value]
    return value


class CodeGraphExecutableAdapter:
    capability_id = "codegraph"
    structural_tools = (
        "codegraph_get_ai_context",
        "codegraph_get_callers",
        "codegraph_get_callees",
        "codegraph_get_dependency_graph",
        "codegraph_analyze_impact",
    )

    def __init__(self, evidence_dir: str, *, codegraph_command: Optional[str] = None, timeout_seconds: int = 120) -> None:
        self.evidence_dir = Path(evidence_dir)
        command = (codegraph_command or os.environ.get("RC8_CODEGRAPH_BIN") or os.environ.get("PFC_CODEGRAPH_BIN") or "codegraph").strip()
        resolved = shutil.which(command)
        if Path(command).is_file():
            resolved = str(Path(command).resolve())
        if not resolved:
            raise CodeGraphAdapterError("CODEGRAPH_COMMAND_NOT_FOUND:%s" % command)
        self.codegraph_command = resolved
        self.timeout_seconds = timeout_seconds

    def _call_tool(self, repo: Path, tool: str, args: Dict[str, object]) -> Dict[str, Any]:
        command = [
            self.codegraph_command,
            "--graph-only",
            "--workspace",
            str(repo),
            "--run-tool",
            tool,
            "--tool-args",
            json.dumps(args, ensure_ascii=False, separators=(",", ":")),
        ]
        started = int(time.time())
        returncode, stdout, stderr, stdout_encoding, stderr_encoding = _run_bytes(
            command,
            cwd=repo,
            timeout_seconds=self.timeout_seconds,
        )
        finished = int(time.time())
        payload: Any = None
        parse_error: Optional[str] = None
        if returncode == 0:
            try:
                payload = _decode_jsonish(json.loads(stdout.strip() or "{}"))
            except ValueError:
                parse_error = "CODEGRAPH_OUTPUT_NOT_JSON"
        return {
            "tool": tool,
            "arguments": args,
            "returncode": returncode,
            "started_at": started,
            "finished_at": finished,
            "stdout_encoding": stdout_encoding,
            "stderr_encoding": stderr_encoding,
            "stderr": stderr[-2000:],
            "payload": payload,
            "parse_error": parse_error,
            "success": returncode == 0 and parse_error is None and isinstance(payload, (dict, list)),
        }

    def execute(
        self,
        *,
        repo_path: str,
        base_ref: str,
        head_ref: str,
        target_file: Optional[str] = None,
        target_line: Optional[int] = None,
        max_points: int = 3,
    ) -> CodeGraphExecutionResult:
        repo = Path(repo_path).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        started = int(time.time())
        snapshot_before = capture_git_snapshot(str(repo))
        changed_files, points = discover_java_query_points(
            str(repo),
            base_ref=base_ref,
            head_ref=head_ref,
            target_file=target_file,
            target_line=target_line,
            max_points=max_points,
        )
        calls: List[Dict[str, Any]] = []
        for point in points:
            uri = (repo / point.file_path).resolve().as_uri()
            zero_line = max(0, point.line_number - 1)
            calls.append(self._call_tool(repo, "codegraph_get_ai_context", {"uri": uri, "line": zero_line, "intent": "explain"}))
            calls.append(self._call_tool(repo, "codegraph_get_callers", {"uri": uri, "line": zero_line, "depth": 1}))
            calls.append(self._call_tool(repo, "codegraph_get_callees", {"uri": uri, "line": zero_line, "depth": 1}))
            calls.append(self._call_tool(repo, "codegraph_get_dependency_graph", {"uri": uri, "direction": "both", "depth": 1}))
            calls.append(self._call_tool(repo, "codegraph_analyze_impact", {"uri": uri, "line": zero_line, "changeType": "modify"}))

        snapshot_after = capture_git_snapshot(str(repo))
        if snapshot_after.snapshot_id != snapshot_before.snapshot_id:
            classification = "CODEGRAPH_SNAPSHOT_STALE"
            state = "FAILED"
        elif not calls or not all(bool(item.get("success")) for item in calls):
            classification = "CODEGRAPH_STRUCTURAL_QUERY_FAILED"
            state = "FAILED"
        else:
            classification = "CODEGRAPH_GRAPH_EVIDENCE_VERIFIED"
            state = "PASS"

        graph_material = {
            "snapshot_id": snapshot_before.snapshot_id,
            "changed_java_files": list(changed_files),
            "query_points": [asdict(item) for item in points],
            "tool_calls": [
                {
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments"),
                    "returncode": item.get("returncode"),
                    "payload": item.get("payload"),
                    "success": item.get("success"),
                }
                for item in calls
            ],
        }
        graph_digest = _canonical_sha256(graph_material)
        payload = {
            "schema_version": 1,
            "state": state,
            "classification": classification,
            "project_dir": str(repo),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "snapshot_before": asdict(snapshot_before),
            "snapshot_after": asdict(snapshot_after),
            "changed_java_files": list(changed_files),
            "query_points": [asdict(item) for item in points],
            "tool_calls": calls,
            "graph_digest": graph_digest,
            "started_at": started,
            "finished_at": int(time.time()),
            "truth_note": "Git is change/snapshot truth; CodeGraph is structural evidence. PASS requires all real read-only structural calls on one unchanged snapshot.",
        }
        evidence_path = self.evidence_dir / "graph-evidence.json"
        temp = evidence_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(str(temp), str(evidence_path))
        return CodeGraphExecutionResult(
            state,
            classification,
            str(repo),
            base_ref,
            head_ref,
            snapshot_before,
            snapshot_after,
            changed_files,
            points,
            tuple(calls),
            graph_digest,
            str(evidence_path),
            started,
            int(time.time()),
        )
