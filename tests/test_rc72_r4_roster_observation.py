"""R4-07 read-only field collector tests; synthetic data is NOT bank proof."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rc7_release.rc72_team_roster_observation import (
    collect_roster_observation, main,
)


class _DshHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(self.path)
        if self.path == "/session/CAPTAIN001":
            payload = {"id": "CAPTAIN001"}
        elif self.path == "/session/status":
            payload = {"CAPTAIN001": {"type": self.server.observed_state}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_dsh():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DshHandler)
    server.requests = []
    server.observed_state = "idle"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, "http://127.0.0.1:%s" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _state(tmp_path, *, count=32):
    directory = tmp_path / ".agent-teams" / "release-team"
    directory.mkdir(parents=True)
    file = directory / "team.json"
    value = dict(id="release-team", name="Release Team",
                 captainSessionId="CAPTAIN001", createdAt=1,
                 members=[dict(name="member-%d" % i, id="", status="idle")
                          for i in range(count)],
                 tasks=[], taskSeq=0, phase="running")
    file.write_text(json.dumps(value), encoding="utf-8")
    return file, value


def _audit(file, url):
    return collect_roster_observation(team_state_file=str(file),
                                      team_id="release-team", dsh_url=url)


def test_32_idle_members_are_a_roster_snapshot_not_32_live_agents(tmp_path, local_dsh):
    server, url = local_dsh
    file, original = _state(tmp_path)
    outcome = _audit(file, url)
    assert outcome["status"] == "ROSTER_SNAPSHOT_AND_LIVE_CAPTAIN_OBSERVED"
    assert outcome["non_removed_member_count"] == 32
    assert outcome["spawned_member_count"] == 0
    assert outcome["idle_or_unspawned_count"] == 32
    assert outcome["field_verified"] is False
    assert outcome["bank_final"] is False
    assert outcome["requires_33rd_add_member_denial"] is True
    assert outcome["requires_native_plugin_signature"] is True
    assert outcome["captain_session_sha256"]
    assert "CAPTAIN001" not in json.dumps(outcome)
    assert server.requests == ["/session/CAPTAIN001", "/session/status"]
    assert json.loads(file.read_text()) == original


@pytest.mark.parametrize("count", [0, 8, 31, 33, 64])
def test_missing_or_extra_roster_member_fails_before_session_probe(tmp_path, local_dsh, count):
    server, url = local_dsh
    file, _ = _state(tmp_path, count=count)
    outcome = _audit(file, url)
    assert outcome["status"] == "HOLD"
    assert outcome["reason"] == "R4_TEAM_ROSTER_NOT_EXACTLY_32"
    assert not server.requests


def test_duplicate_name_and_member_session_are_rejected(tmp_path, local_dsh):
    server, url = local_dsh
    file, data = _state(tmp_path)
    data["members"][1]["name"] = "member-0"
    file.write_text(json.dumps(data))
    assert _audit(file, url)["reason"] == "R4_TEAM_MEMBER_IDENTITY_INVALID"
    data["members"][1]["name"] = "member-1"
    data["members"][0]["id"] = "MEMBER0001"
    data["members"][1]["id"] = "MEMBER0001"
    file.write_text(json.dumps(data))
    assert _audit(file, url)["reason"] == "R4_TEAM_MEMBER_SESSION_DUPLICATE_OR_INVALID"
    assert not server.requests


def test_removed_member_does_not_count_toward_capacity(tmp_path, local_dsh):
    server, url = local_dsh
    file, data = _state(tmp_path)
    data["members"][0]["status"] = "removed"
    file.write_text(json.dumps(data))
    assert _audit(file, url)["reason"] == "R4_TEAM_ROSTER_NOT_EXACTLY_32"


def test_invalid_captain_session_and_non_loopback_refused(tmp_path, local_dsh):
    server, url = local_dsh
    file, data = _state(tmp_path)
    data["captainSessionId"] = "not/allowed"
    file.write_text(json.dumps(data))
    assert _audit(file, url)["reason"] == "R4_TEAM_CAPTAIN_SESSION_INVALID"
    data["captainSessionId"] = "CAPTAIN001"
    file.write_text(json.dumps(data))
    assert _audit(file, "http://example.com:4096")["reason"] == "R4_DSH_LOOPBACK_PROBE_REQUIRED"
    assert not server.requests


def test_captain_status_must_be_observable_and_real(tmp_path, local_dsh):
    server, url = local_dsh
    file, _ = _state(tmp_path)
    server.observed_state = "unknown"
    outcome = _audit(file, url)
    assert outcome["reason"] == "R4_DSH_LIVE_CAPTAIN_STATUS_NOT_PROVEN"
    assert outcome["field_verified"] is False


def test_cli_writes_bounded_non_sensitive_hold_or_observation(tmp_path, local_dsh):
    _, url = local_dsh
    file, _ = _state(tmp_path)
    out = tmp_path / "receipt.json"
    code = main(["--team-state-file", str(file), "--team-id", "release-team",
                 "--dsh-url", url, "--output", str(out)])
    assert code == 0
    record = json.loads(out.read_text())
    assert record["bank_final"] is False
    assert "member-0" not in out.read_text()
    assert "CAPTAIN001" not in out.read_text()
    code = main(["--team-state-file", str(file), "--team-id", "release-team",
                 "--dsh-url", "http://example.com:1234", "--output", str(out)])
    assert code == 2
    assert json.loads(out.read_text())["status"] == "HOLD"

def test_cli_never_overwrites_native_team_json_or_its_state_directory(tmp_path, local_dsh):
    _server, url = local_dsh
    file, original = _state(tmp_path)
    state_before = file.read_bytes()
    for forbidden in (file, file.parent / "receipt.json",
                      file.parent.parent / "receipt.json"):
        code = main(["--team-state-file", str(file),
                     "--team-id", "release-team", "--dsh-url", url,
                     "--output", str(forbidden)])
        assert code == 2
        assert file.read_bytes() == state_before
        if forbidden != file:
            assert not forbidden.exists()
    assert json.loads(file.read_text()) == original
    # A summary outside the native state root remains a valid JSON file.
    out = tmp_path / "audit" / "report.json"
    assert main(["--team-state-file", str(file),
                 "--team-id", "release-team", "--dsh-url", url,
                 "--output", str(out)]) == 0
    assert json.loads(out.read_text())["field_verified"] is False
    assert not list(out.parent.glob(".r4-roster-*.tmp"))


def test_cli_disallows_output_symlink_to_native_team_state(tmp_path, local_dsh):
    _server, url = local_dsh
    file, _ = _state(tmp_path)
    out = tmp_path / "alias.json"
    try:
        out.symlink_to(file)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this runner")
    before = file.read_bytes()
    assert main(["--team-state-file", str(file),
                 "--team-id", "release-team", "--dsh-url", url,
                 "--output", str(out)]) == 2
    assert file.read_bytes() == before
    assert out.is_symlink()


def test_team_state_rejects_symlinked_workspace_or_state_dir_ancestor(tmp_path, local_dsh):
    _server, url = local_dsh
    file, _ = _state(tmp_path)
    state_root = file.parent.parent
    real_root = tmp_path / ".agent-teams-real"
    state_root.rename(real_root)
    alias = tmp_path / ".agent-teams"
    try:
        alias.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        real_root.rename(state_root)
        pytest.skip("directory symlink creation not permitted on this runner")
    aliased_file = alias / "release-team" / "team.json"
    outcome = _audit(aliased_file, url)
    assert outcome["status"] == "HOLD"
    assert outcome["reason"] == "R4_TEAM_STATE_PATH_SYMLINK_FORBIDDEN"
    assert not _server.requests


def test_cli_rejects_output_parent_symlink_into_native_state_root(tmp_path, local_dsh):
    _server, url = local_dsh
    file, _ = _state(tmp_path)
    state_root = file.parent.parent
    alias = tmp_path / "state-alias"
    try:
        alias.symlink_to(state_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation not permitted on this runner")
    protected = file.read_bytes()
    output = alias / "release-team" / "receipt.json"
    assert main(["--team-state-file", str(file), "--team-id", "release-team",
                 "--dsh-url", url, "--output", str(output)]) == 2
    assert file.read_bytes() == protected
    assert not output.exists()


def test_output_dotdot_cannot_escape_native_state_root_check(tmp_path, local_dsh):
    _server, url = local_dsh
    file, _ = _state(tmp_path)
    protected = file.read_bytes()
    output = file.parent.parent / "other" / ".." / "release-team" / "receipt.json"
    assert main(["--team-state-file", str(file), "--team-id", "release-team",
                 "--dsh-url", url, "--output", str(output)]) == 2
    assert file.read_bytes() == protected
    assert not (file.parent / "receipt.json").exists()

