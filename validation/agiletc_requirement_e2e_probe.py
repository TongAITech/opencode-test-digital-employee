"""Run the real AgileTC Requirement producer and independent evaluator with RC7 truth gates.

Validation-only. The second bridge dispatch is stopped only after Requirement
producer output has been independently reviewed and applied to R1. This keeps
Code Analysis out of the probe while preserving the production worker,
authority, MCP, handoff, candidate persistence and deterministic evaluator path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import validation.agiletc_rc7_fullflow as scenario

from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.bank_dsh_tool_policy import FIELD_NODE_POLICIES
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge as _BaseBridge


class _RequirementE2ELauncher(Rc7AuthorizedDshHeadlessWorkerLauncher):
    def __init__(self, *args, **kwargs):
        kwargs["timeout_seconds"] = int(os.environ.get("PFC_REQUIREMENT_PROBE_TIMEOUT_SECONDS", "180"))
        super().__init__(*args, **kwargs)

    def execute(self, assignment, prompt):
        state_dir = Path(os.environ["PFC_AITEST_STATE_DIR"]).resolve()
        audit = state_dir.parent / "requirement-e2e-assignments.jsonl"
        audit.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "mission_id": assignment.mission_id,
            "assignment_id": assignment.assignment_id,
            "worker_instance_id": assignment.worker_instance_id,
            "agent_id": assignment.agent_id,
            "role": assignment.identity.role,
            "phase": assignment.identity.phase,
            "lease_id": assignment.lease.lease_id,
            "allowed_tools": list(assignment.allowed_tools),
            "allowed_artifact_types": list(assignment.allowed_artifact_types),
            "timeout_seconds": self.timeout_seconds,
        }
        with audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return super().execute(assignment, prompt)


class _StopAfterRequirementEvaluationBridge(_BaseBridge):
    def __init__(self, control, launcher, *, node_policies=None):
        super().__init__(
            control,
            launcher,
            node_policies=FIELD_NODE_POLICIES if node_policies is None else node_policies,
        )
        self._dispatch_count = 0

    def run_next(self):
        self._dispatch_count += 1
        if self._dispatch_count > 1:
            raise RuntimeError("REQUIREMENT_EVALUATOR_PROBE_COMPLETE")
        return super().run_next()


def main() -> int:
    scenario.DshHeadlessWorkerLauncher = _RequirementE2ELauncher
    scenario.DshTaskWorkerBridge = _StopAfterRequirementEvaluationBridge
    return scenario.main()


if __name__ == "__main__":
    raise SystemExit(main())
