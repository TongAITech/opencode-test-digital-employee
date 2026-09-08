"""Read explicitly referenced evidence pages without injecting whole files.

Only mission-scoped evidence under the canonical durable root is readable.
Evidence files are supporting bytes, never a replacement for R1 Runtime Truth.
No arbitrary path, host configuration, database, or directory traversal surface
is exposed. Indexes/digests are calculated incrementally and are not persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

from .canonical_runtime import canonical_db_path, create_canonical_runtime
from .r2_1.contracts import validate_secret_boundary

MAX_PAGE_BYTES = 4096
MAX_RESPONSE_BYTES = 16384
_SENSITIVE = re.compile(r'(?i)(?:"?(?:password|passwd|api[_-]?key|authorization|cookie|token|access[_-]?token|secret|private[_-]?key)"?\s*[:=]|bearer\s+|-----BEGIN .*PRIVATE KEY)')
_SECRET_MARKERS = (b"password", b"passwd", b"pwd", b"api", b"authorization", b"cookie", b"token", b"secret", b"private", b"bearer", b"begin", b"basic", b"otp", b"mfa")


def mission_evidence_directory(durable_root: Path, mission_id: str) -> Path:
    # Canonical R1 IDs contain colons, which are invalid directory-name
    # characters on Windows. Keep the original identity in R1 and API results;
    # use its full digest only as the portable evidence storage address.
    if not isinstance(mission_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", mission_id):
        raise ValueError("BOUNDED_EVIDENCE_MISSION_INVALID")
    return Path(durable_root).resolve() / "evidence" / hashlib.sha256(mission_id.encode("utf-8")).hexdigest()


def require_router_session(composed, session_id: str) -> None:
    session = composed.core_state.session(session_id)
    state = composed.extension_state("g2_1_session_control")
    provisions = [p for p in state.provisions if p.status == "BOUND" and p.external_session_id == session_id]
    if session is None or session.status.value != "OPEN" or len(provisions) != 1:
        raise ValueError("BOUNDED_EVIDENCE_ROUTER_SESSION_REQUIRED")
    provision = provisions[0]
    if not provision.logical_agent_id or session.attributes.get("logical_agent_id", provision.logical_agent_id) != provision.logical_agent_id:
        raise ValueError("BOUNDED_EVIDENCE_ROUTER_SESSION_REQUIRED")
    if provision.task_id is None:
        if provision.role != "PLANNER" or provision.phase not in {"PLANNING", "PLANNING_ROTATION"}:
            raise ValueError("BOUNDED_EVIDENCE_ROUTER_SESSION_REQUIRED")
        return
    route = state.route(provision.task_id)
    latest = composed.extension_state("r1_3b_execution_resume").latest_attempt(provision.task_id)
    from .g2_1.router import SessionRouter
    if route is None or route.role != provision.role or route.agent_name != provision.agent_name or provision.logical_agent_id != SessionRouter.logical_agent_id(provision.agent_name, provision.task_id) or latest is None or latest.runtime_session_id != session_id or (provision.root_attempt_id is not None and latest.root_attempt_id != provision.root_attempt_id):
        raise ValueError("BOUNDED_EVIDENCE_CURRENT_ATTEMPT_REQUIRED")


def read_evidence_page(durable_root: Path, mission_id: str, source_ref: str, *, offset: int = 0,
                       limit: int = MAX_PAGE_BYTES, expected_sha256: str | None = None) -> dict:
    """Return one UTF-8 byte page and immutable reference metadata, max 16 KiB.

    The digest and secret scan stream the source in fixed blocks. A source
    containing recognized secret material fails closed before returning text.
    Pagination is pinned with expected_sha256 to detect concurrent replacement.
    """
    expected_root = mission_evidence_directory(durable_root, mission_id)
    if not isinstance(source_ref, str) or not source_ref.startswith("evidence:"):
        raise ValueError("BOUNDED_EVIDENCE_REFERENCE_REQUIRED")
    relative = source_ref[len("evidence:"):]
    parts = PurePosixPath(relative)
    if not relative or len(relative) > 512 or parts.is_absolute() or any(p in {".", ".."} for p in relative.split("/")) or "\\" in relative or ":" in relative:
        raise ValueError("BOUNDED_EVIDENCE_PATH_FORBIDDEN")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_BYTES:
        raise ValueError("BOUNDED_EVIDENCE_PAGE_BUDGET_REQUIRED")
    if offset > 0 and (not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise ValueError("BOUNDED_EVIDENCE_CONTINUATION_HASH_REQUIRED")
    root = expected_root.resolve()
    # Neither evidence/ nor its Mission folder may redirect, even to another
    # Mission inside the same durable root (Windows junctions included).
    if root != expected_root:
        raise ValueError("BOUNDED_EVIDENCE_PATH_FORBIDDEN")
    source = root.joinpath(*parts.parts).resolve()
    if not source.is_relative_to(root) or not source.is_file() or source.suffix.lower() not in {".jsonl", ".json", ".txt", ".log", ".md"}:
        raise ValueError("BOUNDED_EVIDENCE_SOURCE_UNAVAILABLE")
    digest = hashlib.sha256()
    tail = b""
    with source.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
            sample = tail + block
            lowered = sample.lower()
            # The byte prefilter covers every literal in both secret regexes;
            # ordinary MB-scale evidence does not pay Python regex costs.
            if not sample.isascii() or any(marker in lowered for marker in _SECRET_MARKERS):
                scan = sample.decode("utf-8", errors="replace")
                if _SENSITIVE.search(scan):
                    raise ValueError("BOUNDED_EVIDENCE_SECRET_MATERIAL_FORBIDDEN")
                validate_secret_boundary(scan)
            tail = block[-256:]
        source_sha256 = digest.hexdigest()
        if expected_sha256 is not None and expected_sha256 != source_sha256:
            raise ValueError("BOUNDED_EVIDENCE_SOURCE_CHANGED")
        if offset > before.st_size:
            raise ValueError("BOUNDED_EVIDENCE_OFFSET_INVALID")
        stream.seek(offset)
        page = stream.read(limit)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("BOUNDED_EVIDENCE_SOURCE_CHANGED")
    # Offsets are bytes. Replacements on split UTF-8 characters are explicit;
    # durable references still identify exact source bytes and page digest.
    result = {"schema": "aitest.bounded-evidence.v1", "truth_source": "R1_EVENT_STREAM",
              "evidence_is_runtime_truth": False, "mission_id": mission_id, "source_ref": source_ref,
              "source_sha256": source_sha256, "source_bytes": before.st_size, "offset": offset,
              "returned_bytes": len(page), "next_offset": offset + len(page) if offset + len(page) < before.st_size else None,
              "page_sha256": hashlib.sha256(page).hexdigest(), "text": page.decode("utf-8", errors="replace"),
              "read_policy": "BOUNDED_PAGE_ONLY", "max_page_bytes": MAX_PAGE_BYTES,
              "continuation": "Use next_offset and expected_sha256; retain evidence references, never concatenate pages into a prompt."}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("BOUNDED_EVIDENCE_RESPONSE_BUDGET_EXCEEDED")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    payload = json.loads(args.payload)
    if set(payload) - {"mission_id", "source_ref", "offset", "limit", "expected_sha256"}:
        raise ValueError("BOUNDED_EVIDENCE_INPUT_INVALID")
    workspace = Path(os.environ["AITEST_WORKSPACE_ROOT"])
    runtime = create_canonical_runtime(workspace)
    composed = runtime.replay_composed(payload["mission_id"])
    require_router_session(composed, os.environ.get("AITEST_HOST_SESSION_ID", ""))
    result = read_evidence_page(canonical_db_path(workspace).parent.parent, **payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
