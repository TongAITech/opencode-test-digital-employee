"""Immutable code-source identity for RC8 code analysis.

CODE_ANALYSIS must never guess a repository path, branch, or revision.  A test
round freezes one or more CodeSourceSnapshot references before a code-analysis
worker may claim work.  Runtime workers may materialize the source differently
on Windows/Git Bash and Linux/bash, but they must prove that the materialized
source matches this identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class CodeSourceSnapshotError(ValueError):
    """Raised when a code-source identity is incomplete or ambiguous."""


@dataclass(frozen=True)
class CodeSourceSnapshot:
    snapshot_id: str
    repository_id: str
    repository_url: str
    commit_sha: str
    application_id: Optional[str] = None
    base_commit_sha: Optional[str] = None
    subpath: Optional[str] = None
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "CodeSourceSnapshot":
        required = {
            "CODE_SOURCE_SNAPSHOT_ID_REQUIRED": self.snapshot_id,
            "CODE_SOURCE_REPOSITORY_ID_REQUIRED": self.repository_id,
            "CODE_SOURCE_REPOSITORY_URL_REQUIRED": self.repository_url,
            "CODE_SOURCE_COMMIT_SHA_REQUIRED": self.commit_sha,
        }
        for error, raw in required.items():
            if not str(raw or "").strip():
                raise CodeSourceSnapshotError(error)
        if self.base_commit_sha is not None and not str(self.base_commit_sha).strip():
            raise CodeSourceSnapshotError("CODE_SOURCE_BASE_COMMIT_SHA_INVALID")
        if self.subpath is not None:
            normalized = self.subpath.replace("\\", "/").strip("/")
            if normalized in {"", ".", ".."} or normalized.startswith("../") or "/../" in normalized:
                raise CodeSourceSnapshotError("CODE_SOURCE_SUBPATH_INVALID")
        return self

    @property
    def identity(self) -> str:
        """Stable identity used by WorkItem/TestRound frozen refs and evidence."""
        self.validate()
        canonical = "\x1f".join(
            [
                self.repository_id.strip(),
                self.repository_url.strip(),
                (self.application_id or "").strip(),
                (self.base_commit_sha or "").strip(),
                self.commit_sha.strip(),
                (self.subpath or "").replace("\\", "/").strip("/"),
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def frozen_ref(self) -> str:
        return f"code-source:{self.snapshot_id}:{self.identity}"

    def proves_materialized_commit(self, actual_commit_sha: str) -> bool:
        """Fail closed: workers must observe the exact frozen commit."""
        self.validate()
        return bool(actual_commit_sha) and actual_commit_sha.strip() == self.commit_sha.strip()
