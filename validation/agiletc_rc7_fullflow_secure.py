"""Secure composition entrypoint for the AgileTC RC7 field validation.

Keep the evidence-producing scenario in agiletc_rc7_fullflow.py, but replace its
legacy generic DSH runtime bindings with the Bank-field authority composition.
This avoids a validation-only fork of the Mission logic while ensuring the real
run exercises the same exact node tool policy used by field workers.
"""
from __future__ import annotations

import validation.agiletc_rc7_fullflow as scenario

from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.bank_dsh_tool_policy import FIELD_NODE_POLICIES
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge as _BaseBridge


class _BankFieldBridge(_BaseBridge):
    def __init__(self, control, launcher, *, node_policies=None):
        super().__init__(
            control,
            launcher,
            node_policies=FIELD_NODE_POLICIES if node_policies is None else node_policies,
        )


def main() -> int:
    scenario.DshHeadlessWorkerLauncher = Rc7AuthorizedDshHeadlessWorkerLauncher
    scenario.DshTaskWorkerBridge = _BankFieldBridge
    return scenario.main()


if __name__ == "__main__":
    raise SystemExit(main())
