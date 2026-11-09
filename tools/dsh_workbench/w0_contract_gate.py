"""W0 design-time contract oracles; NOT a production workbench endpoint.

Only original first-party implementation. Does not include upstream dsh-qa code.
The license policy intentionally fails closed for the bank distribution scenario.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence


class ContractViolation(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractViolation(code)


def _ids(value: Any) -> List[str]:
    _require(isinstance(value, list), "INVALID_SCOPE")
    _require(all(isinstance(x, str) and x.strip() for x in value), "INVALID_SCOPE")
    _require(len(value) == len(set(value)), "INVALID_SCOPE")
    return value


def legal_scope_rows(
    scope: Mapping[str, Any],
    relation_rows: Sequence[Mapping[str, Any]],
    authorized_projects: Iterable[str],
) -> List[Dict[str, Any]]:
    """Select only authoritative tuples, never a requirement/version Cartesian product.

    relation_rows are a fixture for the proposed B-group relational store, NOT live R1.
    A null sst_id means the requirement-version pair exists but SST is not yet split.
    """
    _require(isinstance(scope, Mapping), "INVALID_SCOPE")
    project_id, batch_id, release_date = (
        scope.get("project_id"), scope.get("batch_id"), scope.get("release_date")
    )
    _require(all(isinstance(x, str) and x.strip() for x in (project_id, batch_id, release_date)),
             "INVALID_SCOPE")
    try:
        _require(date.fromisoformat(release_date).isoformat() == release_date, "INVALID_SCOPE")
    except ValueError as exc:
        raise ContractViolation("INVALID_SCOPE") from exc
    _require(project_id in set(authorized_projects), "FORBIDDEN")
    requirements = _ids(scope.get("requirement_ids", []))
    versions = _ids(scope.get("system_version_ids", []))
    ssts = _ids(scope.get("sst_ids", []))
    batch_rows = [dict(r) for r in relation_rows if r.get("batch_id") == batch_id]
    _require(bool(batch_rows), "RESOURCE_NOT_FOUND")
    _require(all(r.get("project_id") == project_id for r in batch_rows), "FORBIDDEN")
    _require(all(r.get("release_date") == release_date for r in batch_rows), "INVALID_SCOPE")
    matching = [
        r for r in batch_rows
        if (not requirements or r.get("requirement_id") in requirements)
        and (not versions or r.get("system_version_id") in versions)
        and (not ssts or r.get("sst_id") in ssts)
    ]
    _require(bool(matching), "ILLEGAL_ASSOCIATION")
    for field, chosen in (
        ("requirement_id", requirements),
        ("system_version_id", versions),
        ("sst_id", ssts),
    ):
        _require(all(any(r.get(field) == item for r in matching) for item in chosen),
                 "ILLEGAL_ASSOCIATION")
    return matching


COMMAND_ACTIONS = frozenset({"pause", "resume", "retry_failed", "request_human_gate"})


def validate_command(
    command: Mapping[str, Any],
    *,
    authenticated_principal: str,
    authorized: bool,
    current_revision: int,
    authorized_scope_ref: str,
) -> Dict[str, Any]:
    """Only validation. Runtime owns atomic persistence, dedup and state transitions."""
    _require(authorized and bool(authenticated_principal), "FORBIDDEN")
    _require(isinstance(command, Mapping), "VALIDATION_ERROR")
    _require("principal" not in command and "authorization" not in command,
             "UNTRUSTED_PRINCIPAL")
    for key in ("command_id", "idempotency_key", "scope_ref", "action", "reason"):
        _require(isinstance(command.get(key), str) and bool(command[key].strip()),
                 "VALIDATION_ERROR")
    _require(command["scope_ref"] == authorized_scope_ref, "FORBIDDEN")
    _require(command["action"] in COMMAND_ACTIONS, "GATE_BLOCKED")
    _require(type(command.get("expected_state_revision")) is int and
             command["expected_state_revision"] >= 0, "VALIDATION_ERROR")
    _require(command["expected_state_revision"] == current_revision,
             "STATE_REVISION_CONFLICT")
    return dict(command)


EVENT_TYPES = frozenset({
    "mission.updated", "workitem.updated", "attempt.created", "evidence.verified",
    "nodegate.updated", "batch.scope_changed", "human_gate.requested",
    "data.source_unavailable",
})


def accept_event(
    state: MutableMapping[str, Any],
    event: Mapping[str, Any],
    *,
    authenticated_project_id: str,
    authenticated_batch_id: str,
) -> bool:
    """Design oracle for a single authorized project/batch SSE stream.

    Caller must discard cursor and re-authorize on a scope switch.
    R1 truth_revision and transport stream revision are independent.
    This is not an HTTP endpoint, event store, or SSE implementation.
    """
    _require(isinstance(event, Mapping), "VALIDATION_ERROR")
    for key in ("event_id", "project_id", "batch_id", "timestamp", "type", "source_ref"):
        _require(isinstance(event.get(key), str) and bool(event[key].strip()), "VALIDATION_ERROR")
    _require(type(event.get("truth_revision")) is int and
             event["truth_revision"] >= 0, "VALIDATION_ERROR")
    _require(bool(authenticated_project_id) and bool(authenticated_batch_id), "FORBIDDEN")
    _require(event["project_id"] == authenticated_project_id and
             event["batch_id"] == authenticated_batch_id, "FORBIDDEN")
    _require(state.get("project_id", authenticated_project_id) == authenticated_project_id and
             state.get("batch_id", authenticated_batch_id) == authenticated_batch_id,
             "EVENT_SCOPE_MISMATCH")
    _require(event["type"] in EVENT_TYPES, "VALIDATION_ERROR")
    rev = event.get("revision")
    _require(type(rev) is int and rev >= 1, "VALIDATION_ERROR")
    try:
        parsed = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "VALIDATION_ERROR")
    except ValueError as exc:
        raise ContractViolation("VALIDATION_ERROR") from exc
    seen = state.setdefault("seen_events", {})
    if event["event_id"] in seen:
        _require(seen[event["event_id"]] == dict(event), "EVENT_CONFLICT")
        return False
    _require(rev == state.get("revision", 0) + 1, "EVENT_REVISION_GAP")
    state["project_id"] = authenticated_project_id
    state["batch_id"] = authenticated_batch_id
    state["revision"] = rev
    seen[event["event_id"]] = dict(event)
    return True


RESTRICTED_ORIGIN = "naodeng/dsh-qa"
RESTRICTED_LICENSE = "polyform-noncommercial"
FIRST_PARTY_ORIGIN = "tong aitech/opencode-test-digital-employee".replace(" ", "")


def _relative_path(name: Any) -> PurePosixPath:
    _require(isinstance(name, str) and bool(name), "UNMANIFESTED_FILE")
    path = PurePosixPath(name)
    segments = name.split("/")
    _require(not path.is_absolute() and "\\" not in name and
             all(part not in ("", ".", "..") for part in segments) and
             all(":" not in part and part == part.rstrip(" .") for part in segments),
             "UNSAFE_PATH")
    return path


def verify_bank_staging(staging: Path, manifest: Mapping[str, Any]) -> int:
    """Fail-closed staging inventory gate; F reviewer must still audit code provenance."""
    _require(staging.is_dir() and not staging.is_symlink(), "STAGING_MISSING")
    _require(manifest.get("use_case") == "bank_commercial", "UNVERIFIED_USE_CASE")
    entries = manifest.get("files")
    _require(isinstance(entries, list) and bool(entries), "EMPTY_MANIFEST")
    staged_paths = list(staging.rglob("*"))
    _require(not any(p.is_symlink() for p in staged_paths), "UNSAFE_PATH")
    actual_files = {
        p.relative_to(staging).as_posix()
        for p in staged_paths if p.is_file()
    }
    declared = set()
    by_name = {}
    for entry in entries:
        _require(isinstance(entry, Mapping), "UNMANIFESTED_FILE")
        path = _relative_path(entry.get("path"))
        name = path.as_posix()
        _require(name not in declared, "DUPLICATE_MANIFEST_ENTRY")
        declared.add(name)
        by_name[name] = entry
        origin = str(entry.get("source_repository") or "").casefold().strip()
        license_id = str(entry.get("license") or "").casefold().strip()
        _require(RESTRICTED_ORIGIN not in origin and
                 RESTRICTED_LICENSE not in license_id,
                 "BLOCKED_LICENSE")
        if entry.get("origin_kind") == "first_party_independent":
            _require(origin == FIRST_PARTY_ORIGIN and
                     bool(entry.get("provenance_review_ref")), "PROVENANCE_NOT_REVIEWED")
        elif entry.get("origin_kind") == "third_party":
            _require(bool(origin) and bool(license_id) and bool(entry.get("license_file")),
                     "THIRD_PARTY_NOTICES_MISSING")
        else:
            raise ContractViolation("UNKNOWN_ORIGIN")
        file_path = staging.joinpath(*path.parts)
        _require(file_path.is_file() and not file_path.is_symlink(), "UNMANIFESTED_FILE")
        data = file_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        _require(entry.get("sha256") == digest, "FILE_HASH_MISMATCH")
        # A copied license/header must not be stripped to make the scan green.
        # Even with clean content, manual provenance review is still mandatory.
        _require(b"polyform noncommercial" not in data.lower(), "BLOCKED_LICENSE")
    _require(actual_files == declared, "UNMANIFESTED_FILE")
    for entry in entries:
        if entry.get("origin_kind") == "third_party":
            notice_path = _relative_path(entry["license_file"]).as_posix()
            _require(notice_path != entry["path"] and notice_path in by_name,
                     "THIRD_PARTY_NOTICES_MISSING")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="W0 commercial staging fail-closed oracle")
    parser.add_argument("--staging", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        count = verify_bank_staging(Path(args.staging), json.loads(Path(args.manifest).read_text(encoding="utf-8")))
    except (ContractViolation, OSError, ValueError) as exc:
        print("W0_LICENSE_GATE_BLOCKED: " + str(exc))
        return 2
    print("W0_STAGING_INVENTORY_PASS files=%s; F_REVIEW_AND_FIELD_GATE_STILL_REQUIRED" % count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
