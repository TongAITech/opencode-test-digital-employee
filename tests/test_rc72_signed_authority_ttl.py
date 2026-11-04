"""RC7.2 signed worker authority has an exclusive expiration boundary.

This checks the actual HMAC tool gate, not a role prompt or broker assertion.
"""
import pytest

from rc6_runtime.authority import AuthorityError
from rc7_runtime.rc72_authority import (
    RC72AuthorityRuntime, REALITY_RECON_WORKER)


def test_signed_task_lease_denies_tool_at_exact_expiration_second():
    authority = RC72AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    identity = authority.issue_identity(
        REALITY_RECON_WORKER, "N1_REALITY", None, 0, "DSH-SESSION-TTL")
    lease = authority.issue_lease(
        identity.worker_id, "mission:M-1/workitem:WI-1",
        [], ["reality-recon-probe"], ttl_seconds=300)
    authority.authorize_tool(
        identity.worker_id, lease.lease_id,
        "reality-recon-probe", now=lease.expires_at - 1)
    with pytest.raises(AuthorityError, match="LEASE_EXPIRED"):
        authority.authorize_tool(
            identity.worker_id, lease.lease_id,
            "reality-recon-probe", now=lease.expires_at)
    # Historical signature verification is allowed only for incident audit,
    # never to resurrect or authorize a tool after expiry.
    authority.validate_historical_lease(identity, lease)



def test_revoked_unknown_worker_never_masks_denial_on_cold_tool_gate():
    """Cold fail-closed authority need not recreate the revoked Worker/Lease."""
    authority = RC72AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    authority.revoke_worker_lease("LEASE-EXPLICITLY-REVOKED")
    assert authority.is_lease_revoked("LEASE-EXPLICITLY-REVOKED")
    assert "OLD-WORKER" not in authority._identities
    assert "LEASE-EXPLICITLY-REVOKED" not in authority._leases
    with pytest.raises(AuthorityError, match="^LEASE_REVOKED$"):
        authority.authorize_tool(
            "OLD-WORKER", "LEASE-EXPLICITLY-REVOKED", "api_http")
    # Unknown, *unrevoked* identities remain unknown; no permissive fallback.
    with pytest.raises(AuthorityError, match="^UNKNOWN_WORKER$"):
        authority.authorize_tool("UNKNOWN-WORKER", "UNKNOWN-LEASE", "api_http")
    assert not authority._identities and not authority._leases
