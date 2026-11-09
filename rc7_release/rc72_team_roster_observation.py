"""R4-07 read-only, offline-friendly evidence collector for a genuine DSH team.

This is not an AgentTeams membership signature, a member creator, a model
invocation or BANK_FINAL.  On-disk roster snapshots can be forged; a local
DSH captain liveness probe alone does not prove membership ownership.
Only independent native AgentTeams proof + the 33rd-member denial can qualify
the actual Field boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from .rc72_dsh_agentteams_host import _NoRedirect


class TeamRosterAuditError(RuntimeError):
    pass


_TEAM_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_ACTIVE = frozenset(("idle", "working"))
_STATES = _ACTIVE | frozenset(("removed",))


def _read_team(path, expected_team):
    if (not _TEAM_ID.fullmatch(expected_team) or path.name != "team.json"
            or path.parent.name != expected_team or path.is_symlink()
            or path.parent.is_symlink() or not path.is_file()):
        raise TeamRosterAuditError("R4_TEAM_STATE_FILE_NOT_TRUSTED")
    try:
        raw = path.read_bytes()
    except OSError:
        raise TeamRosterAuditError("R4_TEAM_STATE_READ_FAILED") from None
    if not raw or len(raw) > 2_000_000:
        raise TeamRosterAuditError("R4_TEAM_STATE_SIZE_INVALID")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise TeamRosterAuditError("R4_TEAM_STATE_JSON_INVALID") from None
    if (not isinstance(data, dict) or data.get("id") != expected_team
            or data.get("phase", "running") != "running"
            or data.get("halted") is True or not isinstance(data.get("members"), list)):
        raise TeamRosterAuditError("R4_TEAM_STATE_SCOPE_OR_PHASE_INVALID")
    captain = data.get("captainSessionId")
    if not isinstance(captain, str) or not _SESSION_ID.fullmatch(captain):
        raise TeamRosterAuditError("R4_TEAM_CAPTAIN_SESSION_INVALID")
    names, spawned, ids, count = set(), set(), set(), 0
    for member in data["members"]:
        if not isinstance(member, dict):
            raise TeamRosterAuditError("R4_TEAM_MEMBER_SHAPE_INVALID")
        name, status, session = (member.get("name"), member.get("status"),
                                 member.get("id"))
        if (not isinstance(name, str) or not name.strip()
                or name.strip().casefold() in names or status not in _STATES
                or not isinstance(session, str)):
            raise TeamRosterAuditError("R4_TEAM_MEMBER_IDENTITY_INVALID")
        names.add(name.strip().casefold())
        if status == "removed":
            continue
        count += 1
        if session:
            if not _SESSION_ID.fullmatch(session) or session == captain or session in ids:
                raise TeamRosterAuditError("R4_TEAM_MEMBER_SESSION_DUPLICATE_OR_INVALID")
            ids.add(session)
            spawned.add(name.strip().casefold())
    return {
        "captain_session_id": captain,
        "non_removed_member_count": count,
        "spawned_member_count": len(spawned),
        "idle_or_unspawned_count": count - len(spawned),
        "team_state_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _live_session(base_url, captain, timeout):
    url = urlsplit(base_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or not url.port or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment
            or type(timeout) not in (int, float) or not 0 < timeout <= 10):
        raise TeamRosterAuditError("R4_DSH_LOOPBACK_PROBE_REQUIRED")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    base = base_url.rstrip("/")

    def get(suffix):
        full = base + suffix
        try:
            with opener.open(Request(full, headers={"Accept": "application/json"}),
                             timeout=timeout) as response:
                if response.status != 200 or response.geturl() != full:
                    raise TeamRosterAuditError("R4_DSH_PROBE_REDIRECT_OR_HTTP")
                raw = response.read(65_537)
        except (OSError, HTTPError, URLError, ValueError):
            raise TeamRosterAuditError("R4_DSH_LIVE_SESSION_PROBE_FAILED") from None
        if len(raw) > 65_536:
            raise TeamRosterAuditError("R4_DSH_PROBE_TOO_LARGE")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise TeamRosterAuditError("R4_DSH_PROBE_INVALID_JSON") from None
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            parsed = parsed["data"]
        if not isinstance(parsed, dict):
            raise TeamRosterAuditError("R4_DSH_PROBE_INVALID_OBJECT")
        return parsed

    found = get("/session/" + quote(captain, safe=""))
    if found.get("id") != captain:
        raise TeamRosterAuditError("R4_DSH_LIVE_CAPTAIN_ID_MISMATCH")
    status = get("/session/status").get(captain)
    if not isinstance(status, dict) or status.get("type") not in ("busy", "idle", "retry"):
        raise TeamRosterAuditError("R4_DSH_LIVE_CAPTAIN_STATUS_NOT_PROVEN")
    return status["type"]


def collect_roster_observation(*, team_state_file, team_id, dsh_url, timeout=3):
    """Read-only host facts, explicitly not a final 32 member qualification."""
    result = {
        "team_id": team_id,
        "expected_non_removed_members": 32,
        "status": "HOLD",
        "field_verified": False,
        "bank_final": False,
        "requires_native_plugin_signature": True,
        "requires_33rd_add_member_denial": True,
        "requires_independent_r1_execution_proof": True,
    }
    try:
        facts = _read_team(Path(team_state_file), team_id)
        if facts["non_removed_member_count"] != 32:
            raise TeamRosterAuditError("R4_TEAM_ROSTER_NOT_EXACTLY_32")
        live = _live_session(dsh_url, facts["captain_session_id"], timeout)
    except (TeamRosterAuditError, TypeError, ValueError) as exc:
        result["reason"] = str(exc)
        return result
    result.update(
        status="ROSTER_SNAPSHOT_AND_LIVE_CAPTAIN_OBSERVED",
        reason="NATIVE_AGENTTEAMS_PROOF_AND_33RD_BOUNDARY_PENDING",
        non_removed_member_count=facts["non_removed_member_count"],
        spawned_member_count=facts["spawned_member_count"],
        idle_or_unspawned_count=facts["idle_or_unspawned_count"],
        team_state_sha256=facts["team_state_sha256"],
        captain_session_sha256=hashlib.sha256(
            facts["captain_session_id"].encode("utf-8")).hexdigest(),
        live_captain_state=live,
    )
    # Do not leak actual bank member or captain IDs in the summary.
    return result


def _safe_output_path(*, team_state_file, output):
    """A read-only probe may write its summary, never the native Team store.

    Outputs must live outside the native AgentTeams state root, with no
    symlinked path component. Even a caller passing team.json as --output
    must not be able to turn observation into an in-place Team mutation.
    """
    source = Path(team_state_file).expanduser().resolve()
    target = Path(output).expanduser().absolute()
    if not target.name or target.exists() and not target.is_file():
        raise TeamRosterAuditError("R4_OBSERVATION_OUTPUT_PATH_UNSAFE")
    if any(item.is_symlink() for item in (target,) + tuple(target.parents)):
        raise TeamRosterAuditError("R4_OBSERVATION_OUTPUT_SYMLINK_FORBIDDEN")
    # Source layout: <workspace>/<stateDir>/<teamId>/team.json
    native_state_root = source.parent.parent
    try:
        target.resolve().relative_to(native_state_root)
    except ValueError:
        pass
    else:
        raise TeamRosterAuditError("R4_OBSERVATION_OUTPUT_INSIDE_NATIVE_STATE")
    return target


def _write_observation_atomic(out, report):
    """Do not leave a half-written summary after a process interruption."""
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=".r4-roster-",
                suffix=".tmp", dir=str(out.parent), delete=False) as fh:
            temp = Path(fh.name)
            fh.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(temp), str(out))
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description="R4-07 real DSH team read-only snapshot audit")
    parser.add_argument("--team-state-file", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--dsh-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = collect_roster_observation(
        team_state_file=args.team_state_file, team_id=args.team_id,
        dsh_url=args.dsh_url)
    try:
        out = _safe_output_path(
            team_state_file=args.team_state_file, output=args.output)
        _write_observation_atomic(out, report)
    except (TeamRosterAuditError, OSError) as exc:
        # A diagnostic must not contain member/captain names, tokens or paths.
        reason = str(exc) if isinstance(exc, TeamRosterAuditError) else "R4_OBSERVATION_OUTPUT_WRITE_FAILED"
        print(reason, file=sys.stderr)
        return 2
    return 0 if report["status"] == "ROSTER_SNAPSHOT_AND_LIVE_CAPTAIN_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
