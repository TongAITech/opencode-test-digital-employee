"""Runtime build identity attestation for RC7 Missions.

A real Mission must be attributable to the immutable RC7 package that actually
ran it.  Final qualification therefore never trusts a caller-supplied commit
alone.  When a Mission is bootstrapped from a delivery package (SOURCE_COMMIT)
or an explicitly identified field runtime (PFC_RC7_SOURCE_COMMIT), this module
persists the exact build identity into the same R1 Event Stream as ordinary
Mission truth.

Absence of identity is allowed during unit/development construction, but real
Mission qualification is fail-closed and will HOLD until this evidence exists.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

from rc6_runtime.truth import TruthRuntime

from .models import Evidence
from .truth_overlay import append_entity


_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
RUNTIME_IDENTITY_KIND = "RC7_RUNTIME_IDENTITY"
RUNTIME_IDENTITY_SOURCE = "runtime://rc7-build"


class RuntimeIdentityError(RuntimeError):
    pass


def _normalize_commit(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    commit = value.strip().lower()
    if not commit:
        return None
    if not _SHA_RE.match(commit):
        raise RuntimeIdentityError("RC7_RUNTIME_SOURCE_COMMIT_INVALID")
    return commit


def resolve_runtime_source_commit() -> Optional[str]:
    """Resolve only identities that are available before Mission work starts.

    We intentionally do not fall back to an arbitrary later `git rev-parse` in
    qualification code: package SOURCE_COMMIT or an explicit field-runtime env
    binding is the build identity that must be present at bootstrap time.
    """

    env_commit = _normalize_commit(os.environ.get("PFC_RC7_SOURCE_COMMIT"))
    if env_commit:
        return env_commit

    package_root = Path(__file__).resolve().parents[1]
    source_file = package_root / "SOURCE_COMMIT"
    if source_file.is_file():
        return _normalize_commit(source_file.read_text(encoding="utf-8"))
    return None


def runtime_identity_evidence_id(mission_id: str, source_commit: str) -> str:
    raw = (mission_id + "\x1f" + source_commit.lower()).encode("utf-8")
    return "EVD-RC7-RUNTIME-ID-%s" % hashlib.sha256(raw).hexdigest()[:20]


def attest_runtime_identity(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    source_commit: Optional[str] = None,
) -> Optional[str]:
    commit = _normalize_commit(source_commit) if source_commit is not None else resolve_runtime_source_commit()
    if commit is None:
        return None
    if not mission_id or not release_id:
        raise RuntimeIdentityError("RC7_RUNTIME_IDENTITY_MISSION_RELEASE_REQUIRED")

    evidence_id = runtime_identity_evidence_id(mission_id, commit)
    existing = truth.query("rc7_evidence", evidence_id=evidence_id)
    if existing:
        if len(existing) != 1:
            raise RuntimeIdentityError("RC7_RUNTIME_IDENTITY_NOT_UNIQUE")
        row = existing[0]
        if (
            row.get("mission_id") != mission_id
            or row.get("kind") != RUNTIME_IDENTITY_KIND
            or row.get("source_ref") != RUNTIME_IDENTITY_SOURCE
            or row.get("content_ref") != "git://%s" % commit
        ):
            raise RuntimeIdentityError("RC7_RUNTIME_IDENTITY_CONFLICT")
        return evidence_id

    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind=RUNTIME_IDENTITY_KIND,
            source_ref=RUNTIME_IDENTITY_SOURCE,
            content_ref="git://%s" % commit,
            subject_refs=[mission_id, release_id],
            content_hash="sha1:%s" % commit,
        ),
        release_id=release_id,
        artifact_version=1,
    )
    return evidence_id
