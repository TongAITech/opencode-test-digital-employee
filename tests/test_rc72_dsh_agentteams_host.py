"""GAP-02: actual loopback DSH session probe plus cryptographic team proof."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
import time

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_release.rc72_dsh_agentteams_host import (
    SignedAgentTeamsCaptain, LocalDshAgentTeamsHost,
)
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, build_truth, start_n1


SESSION = 'session-real-dsh-captain-001'
TEAM = 'TEAM-REAL-DSH-001'


def _local_server(*, alive=True, correct_id=True):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/session/' + SESSION:
                data = {'id': SESSION if correct_id else 'session-foreign-captain'}
            elif self.path == '/session/status':
                data = {SESSION: {'type': 'busy'}} if alive else {}
            else:
                self.send_error(404)
                return
            payload = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            return

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _host(server):
    membership_key = RC72AuthorityRuntime(b'test-dsh-agentteams-signed-plugin-key')
    host_key = RC72AuthorityRuntime(b'test-dsh-host-independent-controller-key')
    host = LocalDshAgentTeamsHost(base_url='http://127.0.0.1:%d' % server.server_port,
                                  membership_authority=membership_key,
                                  host_authority=host_key)
    return host, membership_key


def _proof(key, **updates):
    attrs = dict(release_id=RELEASE, source_commit=COMMIT,
                 release_batch_id=BATCH, mission_id=MISSION,
                 team_id=TEAM, captain_session_id=SESSION, dsh_session_id=SESSION,
                 role='CAPTAIN', observed_at=int(time.time()), signature='PENDING')
    attrs.update(updates)
    unsigned = SignedAgentTeamsCaptain(**attrs)
    return replace(unsigned, signature=key._sign(unsigned.signed_fields()))


def _bind(host, truth, proof):
    return host.bind(truth=truth, release_id=RELEASE, source_commit=COMMIT,
                     release_batch_id=BATCH, proof=proof,
                     role_profiles={'L3_EXECUTE': ('api_http',)},
                     approved_capabilities=('api_http',))


def test_real_local_http_session_and_signed_membership_bootstraps_once_and_reenters(tmp_path):
    truth = build_truth(tmp_path)
    start_n1(truth)
    server = _local_server()
    try:
        host, membership_key = _host(server)
        proof = _proof(membership_key)
        first = _bind(host, truth, proof)
        assert first.captain_session_id == SESSION
        owner = truth.query('rc72_captain_dispatch_lease', mission_id=MISSION)[0]
        assert owner['team_id'] == TEAM and owner['generation'] == 1
        assert first.captain_lease_id == owner['lease_id']
        before = truth.store.path.read_bytes()
        cold = TruthRuntime(truth.store.path)
        second = _bind(host, cold, proof)
        assert second.captain_lease_id == first.captain_lease_id
        assert truth.store.path.read_bytes() == before
        assert not cold.query('execution_attempt')
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('kind,reason', [
    ('wrong_signature', 'TEAM_SIGNATURE_INVALID'),
    ('untrusted_role', 'TEAM_SCOPE_OR_FRESHNESS_INVALID'),
    ('stale', 'TEAM_SCOPE_OR_FRESHNESS_INVALID'),
    ('different_session', 'TEAM_SCOPE_OR_FRESHNESS_INVALID'),
    ('not_active', 'ACTIVE_SESSION_NOT_PROVEN'),
    ('wrong_provider_session', 'ACTUAL_SESSION_ID_MISMATCH'),
])
def test_no_captain_for_signed_scope_failure_or_nonlive_dsh(tmp_path, kind, reason):
    truth = build_truth(tmp_path)
    start_n1(truth)
    server = _local_server(alive=(kind != 'not_active'),
                           correct_id=(kind != 'wrong_provider_session'))
    try:
        host, key = _host(server)
        proof = _proof(key)
        if kind == 'wrong_signature':
            proof = replace(proof, signature='x' * 64)
        elif kind == 'untrusted_role':
            proof = _proof(key, role='WORKER')
        elif kind == 'stale':
            proof = _proof(key, observed_at=int(time.time()) - 60)
        elif kind == 'different_session':
            proof = _proof(key, captain_session_id='session-unknown-other')
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='C07_DSH_HOST_' + reason):
            _bind(host, truth, proof)
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc72_captain_dispatch_lease') == []
    finally:
        server.shutdown()
        server.server_close()


def test_config_session_name_cannot_replace_a_signed_agentteams_proof(tmp_path):
    truth = build_truth(tmp_path)
    start_n1(truth)
    server = _local_server()
    try:
        host, _key = _host(server)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='SIGNED_TEAM_MEMBERSHIP_REQUIRED'):
            _bind(host, truth, {'captain_session_id': SESSION, 'team_id': TEAM})
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc72_captain_dispatch_lease') == []
    finally:
        server.shutdown()
        server.server_close()


def test_host_disallows_remote_sessions_and_shared_signer():
    membership_key = RC72AuthorityRuntime(b'identity-scope-test-key')
    with pytest.raises(ContractError, match='LOOPBACK_ONLY'):
        LocalDshAgentTeamsHost(base_url='http://example.org:4096',
                               membership_authority=membership_key,
                               host_authority=RC72AuthorityRuntime(b'other-test-key-separate'))
    with pytest.raises(ContractError, match='SEPARATE_AUTHORITIES_REQUIRED'):
        LocalDshAgentTeamsHost(base_url='http://127.0.0.1:4096',
                               membership_authority=membership_key,
                               host_authority=membership_key)
