"""Diagnostic entrypoint that runs the real AgileTC Mission through the Requirement producer only.

This is validation-only. It reuses the production RC7 authorized launcher and
Bank-field node policy, but bounds the worker to a shorter diagnostic timeout
and stops before the independent reviewer once producer evidence has been
captured. No partial output is promoted to accepted Task evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import validation.agiletc_rc7_fullflow as scenario

from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.bank_dsh_tool_policy import FIELD_NODE_POLICIES
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge as _BaseBridge


class _RequirementProbeLauncher(Rc7AuthorizedDshHeadlessWorkerLauncher):
    def __init__(self, *args, **kwargs):
        kwargs["timeout_seconds"] = int(os.environ.get("PFC_REQUIREMENT_PROBE_TIMEOUT_SECONDS", "180"))
        super().__init__(*args, **kwargs)

    def execute(self, assignment, prompt):
        # Validation-only provider compatibility seam. Keep it opt-in: the
        # real runner proved the local Qwen /no_think soft switch does not
        # guarantee direct action, so it must never be a hidden qualification
        # default. Any future provider experiment can still set the env var
        # explicitly without changing the production worker contract.
        suffix = os.environ.get("PFC_REQUIREMENT_PROBE_USER_SUFFIX", "").strip()
        effective_prompt = prompt.rstrip()
        if suffix:
            effective_prompt += "\n" + suffix

        state_dir = Path(os.environ["PFC_AITEST_STATE_DIR"]).resolve()
        out = state_dir.parent / "requirement-probe-input.json"
        original_encoded = prompt.encode("utf-8")
        effective_encoded = effective_prompt.encode("utf-8")
        out.write_text(
            json.dumps(
                {
                    "mission_id": assignment.mission_id,
                    "assignment_id": assignment.assignment_id,
                    "worker_instance_id": assignment.worker_instance_id,
                    "lease_id": assignment.lease.lease_id,
                    "allowed_tools": list(assignment.allowed_tools),
                    "allowed_tool_count": len(assignment.allowed_tools),
                    "prompt_chars": len(prompt),
                    "prompt_utf8_bytes": len(original_encoded),
                    "prompt_sha256": hashlib.sha256(original_encoded).hexdigest(),
                    "effective_prompt_chars": len(effective_prompt),
                    "effective_prompt_utf8_bytes": len(effective_encoded),
                    "effective_prompt_sha256": hashlib.sha256(effective_encoded).hexdigest(),
                    "user_suffix_enabled": bool(suffix),
                    "user_suffix_chars": len(suffix),
                    "timeout_seconds": self.timeout_seconds,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return super().execute(assignment, effective_prompt)


class _BankFieldBridge(_BaseBridge):
    def __init__(self, control, launcher, *, node_policies=None):
        super().__init__(
            control,
            launcher,
            node_policies=FIELD_NODE_POLICIES if node_policies is None else node_policies,
        )


class _StopBeforeRequirementReviewer:
    def __init__(self, *args, **kwargs):
        pass

    def evaluate_and_apply(self, *args, **kwargs):
        raise RuntimeError("REQUIREMENT_PRODUCER_PROBE_COMPLETE")


def main() -> int:
    scenario.DshHeadlessWorkerLauncher = _RequirementProbeLauncher
    scenario.DshTaskWorkerBridge = _BankFieldBridge
    scenario.DshRequirementEvaluator = _StopBeforeRequirementReviewer
    return scenario.main()


if __name__ == "__main__":
    raise SystemExit(main())
