"""GAP-02 actual local DSH AgentTeams Captain observation -> signed R1 Host.

No title/prompt/config text can invent Team/Captain. The AgentTeams plugin
must produce a separately authenticated Captain membership proof; this
adapter independently probes the real local OpenCode/DSH session API before
minting a short-lived Host observation and entering existing Captain fencing.

This file does NOT auto-create a DSH Team. If the actual DSH API or native
AgentTeams proof is unavailable it fails closed, retaining original R1.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hmac
import json
import re
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_captain_dispatch_fencing import install_captain_dispatch_overlay
from .rc72_captain_host_reentry import (
    ObservedDshCaptain, ObservedDshCaptainStartup,
    bootstrap_host_captain, reenter_host_captain,
)


@dataclass(frozen=True)
class SignedAgentTeamsCaptain:
    """Signed membership from the DSH AgentTeams control-plane, not LLM text."""

    release_id: str
    source_commit: str
    release_batch_id: str
    mission_id: str
    team_id: str
    captain_session_id: str
    dsh_session_id: str
    role: str
    observed_at: int
    signature: str

    def signed_fields(self):
        return dict(purpose='DSH_AGENTTEAMS_CAPTAIN_MEMBERSHIP_V1',
                    release_id=self.release_id, source_commit=self.source_commit,
                    release_batch_id=self.release_batch_id, mission_id=self.mission_id,
                    team_id=self.team_id, captain_session_id=self.captain_session_id,
                    dsh_session_id=self.dsh_session_id, role=self.role,
                    observed_at=self.observed_at)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalDshAgentTeamsHost:
    """One read-only real DSH API check + separately signed AgentTeams proof."""

    def __init__(self, *, base_url, membership_authority, host_authority,
                 timeout_seconds=3, now=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment or not parsed.port):
            raise ContractError('C07_DSH_HOST_LOOPBACK_ONLY')
        if (type(membership_authority) is not RC72AuthorityRuntime
                or type(host_authority) is not RC72AuthorityRuntime
                or membership_authority is host_authority):
            raise ContractError('C07_DSH_HOST_SEPARATE_AUTHORITIES_REQUIRED')
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 10:
            raise ContractError('C07_DSH_HOST_BOUNDED_TIMEOUT_REQUIRED')
        self.base_url = base_url.rstrip('/')
        self.membership_authority = membership_authority
        self.host_authority = host_authority
        self.timeout = timeout_seconds
        self.now = now or (lambda: int(time.time()))
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _get(self, path):
        url = self.base_url + path
        try:
            with self._opener.open(
                Request(url, headers={'Accept': 'application/json'}),
                timeout=self.timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ContractError('C07_DSH_HOST_UNTRUSTED_HTTP_REDIRECT')
                raw = response.read(65537)
        except (OSError, HTTPError, URLError, ValueError):
            raise ContractError('C07_DSH_HOST_SESSION_PROBE_FAILED') from None
        if len(raw) > 65536:
            raise ContractError('C07_DSH_HOST_RESPONSE_TOO_LARGE')
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError):
            raise ContractError('C07_DSH_HOST_RESPONSE_INVALID') from None
        if isinstance(data, dict) and isinstance(data.get('data'), dict):
            return data['data']
        if not isinstance(data, dict):
            raise ContractError('C07_DSH_HOST_RESPONSE_NOT_OBJECT')
        return data

    def _verify_live_membership(self, *, proof, truth, release_id,
                                source_commit, release_batch_id):
        if (type(proof) is not SignedAgentTeamsCaptain
                or type(truth) is not TruthRuntime):
            raise ContractError('C07_DSH_HOST_SIGNED_TEAM_MEMBERSHIP_REQUIRED')
        if (not isinstance(proof.signature, str)
                or not hmac.compare_digest(
                    proof.signature, self.membership_authority._sign(proof.signed_fields()))):
            raise ContractError('C07_DSH_HOST_TEAM_SIGNATURE_INVALID')
        if (proof.release_id != release_id or proof.source_commit != source_commit
                or proof.release_batch_id != release_batch_id or proof.role != 'CAPTAIN'
                or not re.fullmatch('[0-9a-f]{40}', source_commit)
                or not isinstance(proof.team_id, str) or not proof.team_id.strip()
                or not isinstance(proof.mission_id, str) or not proof.mission_id.strip()
                or proof.dsh_session_id != proof.captain_session_id
                or not isinstance(proof.dsh_session_id, str)
                or not re.fullmatch('[A-Za-z0-9_-]{8,128}', proof.dsh_session_id)
                or type(proof.observed_at) is not int
                or not 0 <= self.now() - proof.observed_at <= 20):
            raise ContractError('C07_DSH_HOST_TEAM_SCOPE_OR_FRESHNESS_INVALID')
        install_captain_dispatch_overlay()
        batches = truth.query('rc72_release_batch', release_batch_id=release_batch_id)
        if (len(batches) != 1 or batches[0].get('release_id') != release_id
                or batches[0].get('mission_id') != proof.mission_id):
            raise ContractError('C07_DSH_HOST_CANONICAL_BATCH_REQUIRED')
        session = self._get('/session/' + quote(proof.dsh_session_id, safe=''))
        if session.get('id') != proof.dsh_session_id:
            raise ContractError('C07_DSH_HOST_ACTUAL_SESSION_ID_MISMATCH')
        # Different DSH builds may omit inactive (idle) sessions from this map.
        # That is not proof of ACTIVE Captain: require an observable live status.
        status = self._get('/session/status')
        active = status.get(proof.dsh_session_id)
        if (not isinstance(active, dict)
                or active.get('type') not in {'busy', 'idle', 'retry'}):
            raise ContractError('C07_DSH_HOST_ACTIVE_SESSION_NOT_PROVEN')
        return batches[0]

    def bind(self, *, truth, release_id, source_commit, release_batch_id,
             proof, role_profiles, approved_capabilities):
        """Observe first, then create/reenter the exact canonical R1 Captain."""
        batch = self._verify_live_membership(
            proof=proof, truth=truth, release_id=release_id,
            source_commit=source_commit, release_batch_id=release_batch_id)
        leases = truth.query('rc72_captain_dispatch_lease', mission_id=batch['mission_id'])
        arguments = dict(
            truth=truth, release_id=release_id, source_commit=source_commit,
            release_batch_id=release_batch_id, host_authority=self.host_authority,
            role_profiles=role_profiles, approved_capabilities=approved_capabilities)
        dsh_ref = 'dsh://session/' + proof.dsh_session_id
        if not leases:
            startup = ObservedDshCaptainStartup(
                release_id=release_id, source_commit=source_commit,
                release_batch_id=release_batch_id, mission_id=proof.mission_id,
                team_id=proof.team_id, captain_session_id=proof.captain_session_id,
                dsh_session_ref=dsh_ref, observed_at=proof.observed_at,
                state='ACTIVE', signature='PENDING')
            startup = replace(startup, signature=self.host_authority._sign(startup.signed_fields()))
            return bootstrap_host_captain(startup=startup, **arguments)
        generation = max(row['generation'] for row in leases)
        current = [row for row in leases if row['generation'] == generation]
        if len(current) != 1:
            raise ContractError('C07_DSH_HOST_ACTIVE_GENERATION_NOT_UNIQUE')
        owner = current[0]
        if (owner['team_id'] != proof.team_id
                or owner['captain_session_id'] != proof.captain_session_id):
            raise ContractError('C07_DSH_HOST_OLD_OR_FOREIGN_CAPTAIN')
        ticket = ObservedDshCaptain(
            release_id=release_id, source_commit=source_commit,
            release_batch_id=release_batch_id, mission_id=proof.mission_id,
            team_id=proof.team_id, captain_session_id=proof.captain_session_id,
            captain_lease_id=owner['lease_id'],
            captain_generation=owner['generation'], dsh_session_ref=dsh_ref,
            observed_at=proof.observed_at, state='ACTIVE', signature='PENDING')
        ticket = replace(ticket, signature=self.host_authority._sign(ticket.signed_fields()))
        return reenter_host_captain(observed=ticket, **arguments)
