from __future__ import annotations

import pytest

from rc6_runtime.authority import AuthorityError
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.dsh_worker_bridge import DEFAULT_NODE_POLICIES


def test_all_default_dsh_policies_fit_rc7_authority_scope() -> None:
    authority = RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    for index, (node, policy) in enumerate(DEFAULT_NODE_POLICIES.items()):
        identity = authority.issue_identity(
            role=policy.role,
            phase=policy.phase,
            layer=None,
            generation=0,
            session_id="session-%s-%s" % (index, node.lower()),
        )
        lease = authority.issue_lease(
            identity.worker_id,
            scope_ref="task:TASK-%s" % node,
            allowed_artifact_types=policy.allowed_artifact_types,
            allowed_tools=policy.allowed_tools,
        )
        for artifact_type in policy.allowed_artifact_types:
            authority.authorize_artifact(identity.worker_id, lease.lease_id, artifact_type)
        for tool_name in policy.allowed_tools:
            authority.authorize_tool(identity.worker_id, lease.lease_id, tool_name)


def test_rc7_worker_role_cannot_escalate_to_acceptance_or_other_node_artifact() -> None:
    authority = RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    identity = authority.issue_identity(
        role="RC7_REQUIREMENT_WORKER",
        phase="ANALYSIS",
        layer=None,
        generation=0,
        session_id="session-requirement",
    )

    with pytest.raises(AuthorityError, match="LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE"):
        authority.issue_lease(
            identity.worker_id,
            scope_ref="task:TASK-REQ",
            allowed_artifact_types=("rc7_requirement_candidate", "rc7_code_candidate"),
            allowed_tools=("filesystem",),
        )

    with pytest.raises(AuthorityError, match="LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE"):
        authority.issue_lease(
            identity.worker_id,
            scope_ref="task:TASK-REQ",
            allowed_artifact_types=("rc7_evaluation",),
            allowed_tools=(),
        )
