"""C10 shared DSH batch cryptographic WorkerAssignment admission.

Scope strings, model prompts and in-memory worker IDs are not authority.  An
actual RC6 DshHeadlessWorkerLauncher must hold the same AuthorityRuntime that
issued the worker identity and signed task lease; validate it *before* model
launch. No fake token/candidate result can elevate tools or extend an expired
lease. The R1 semantic Task/Attempt and raw-tool proofs remain independent.
"""
from __future__ import annotations

from typing import Any, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import (
    AuthorityError, AuthorityRuntime, TaskLease, WorkerIdentity,
)

from .models import ContractError


class NativeBatchAuthorityError(ContractError):
    pass


def require_signed_batch_authority(
    launcher: DshHeadlessWorkerLauncher,
    assignment: Any, *,
    expected_scope: str,
) -> Tuple[str, ...]:
    if not isinstance(launcher, DshHeadlessWorkerLauncher):
        raise NativeBatchAuthorityError("NATIVE_BATCH_REAL_DSH_LAUNCHER_REQUIRED")
    authority = getattr(launcher, "authority", None)
    identity = getattr(assignment, "identity", None)
    lease = getattr(assignment, "lease", None)
    if (
        not isinstance(authority, AuthorityRuntime)
        or not isinstance(identity, WorkerIdentity)
        or not isinstance(lease, TaskLease)
    ):
        raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_RUNTIME_AUTHORITY_REQUIRED")
    if (
        not isinstance(expected_scope, str) or not expected_scope
        or getattr(assignment, "scope", None) != expected_scope
        or lease.scope_ref != expected_scope
    ):
        raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_SCOPE_MISMATCH")
    worker_id = getattr(assignment, "worker_instance_id", None)
    if worker_id != identity.worker_id or worker_id != lease.worker_id:
        raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_WORKER_MISMATCH")
    tools = getattr(assignment, "allowed_tools", None)
    artifacts = getattr(assignment, "allowed_artifact_types", None)
    if (
        not isinstance(tools, (list, tuple))
        or not tools
        or any(not isinstance(tool, str) or not tool.strip() for tool in tools)
        or len(set(tools)) != len(tools)
        or set(tools) != set(lease.allowed_tools)
        or not isinstance(artifacts, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in artifacts)
        or set(artifacts) != set(lease.allowed_artifact_types)
    ):
        raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_CAPABILITY_SCOPE_MISMATCH")
    # IMPORTANT: authorize_tool() loads a lease by ID from its registry.
    # Calling it alone does NOT prove that the caller-provided lease object
    # was unmodified. Verify that *this exact signed value* is issuer-owned
    # and HMAC-valid before relying on registry-based tool authorization.
    try:
        if (
            authority._require_identity(worker_id) != identity
            or authority._require_lease(lease.lease_id) != lease
        ):
            raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_REGISTRY_MISMATCH")
        authority._validate_lease(identity, lease)
        for tool in tools:
            authority.authorize_tool(worker_id, lease.lease_id, tool)
    except (AuthorityError, ValueError) as exc:
        raise NativeBatchAuthorityError("NATIVE_BATCH_SIGNED_LEASE_DENIED") from exc
    return tuple(tools)
