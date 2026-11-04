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
