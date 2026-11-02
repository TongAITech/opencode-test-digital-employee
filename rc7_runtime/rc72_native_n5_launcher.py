"""Native N5 DSH launcher whose MCP effects execute behind a live parent gate."""
import json

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.process_environment import scoped_process_environment
from .models import ContractError
from .rc72_native_n5_tool_gate import NativeN5ToolGate


class NativeN5FencedDshLauncher(DshHeadlessWorkerLauncher):
    def __init__(self, *, handlers, **kwargs):
        super().__init__(**kwargs)
        self.handlers = tuple(handlers)
        self.native_service, self._native_gate, self._native_output = None, None, None
        self._underlying_runner = self.command_runner
        self.command_runner = self._run_isolated

    def bind_native_service(self, service):
        from .rc72_n5_existing_data_repair import ExistingDataRepairService
        if (not isinstance(service, ExistingDataRepairService) or service.truth is not self.truth
                or service.authority is not self.authority or service.preparation.release_id != self.release_id
                or self._native_gate is not None):
            raise ContractError('NATIVE_N5_LAUNCHER_SERVICE_MISMATCH')
        self.native_service = service
        return self

    def _run_isolated(self, command, **kwargs):
        # Ignore the base launcher's ambient copy. Only this launcher's explicit
        # task/provider configuration and current invocation projection enter.
        explicit = dict(self.env)
        if any('CAPTAIN' in key.upper() or 'COORDINATOR' in key.upper() or 'SIGNING_KEY' in key.upper()
               for key in explicit):
            raise ContractError('NATIVE_WORKER_CONTROL_CREDENTIAL_FORBIDDEN')
        kwargs['env'] = scoped_process_environment(explicit,
            home=self.state_root / 'native-worker-home' / self._native_gate.gate_id)
        return self._underlying_runner(command, **kwargs)

    def execute(self, assignment, prompt):
        if self.native_service is None or self._native_gate is not None:
            raise ContractError('NATIVE_N5_LIVE_SERVICE_REQUIRED')
        gate = NativeN5ToolGate(self.native_service, assignment, self.handlers).open()
        self._native_gate, self._native_output = gate, None
        context = dict(mission_id=gate.scope['mission_id'], task_id=gate.scope['workitem_id'], worker_id=gate.scope['worker_id'])
        projected = dict(gate.environment(), PFC_RC7_MCP_MISSION_ID=context['mission_id'],
            PFC_RC7_MCP_TASK_ID=context['task_id'], PFC_RC7_MCP_WORKER_ID=context['worker_id'],
            PFC_RC7_MCP_LEASE_ID=assignment.lease.lease_id, PFC_RC7_MCP_SCOPE_REF=assignment.scope,
            PFC_RC7_DSH_ALLOWED_TOOLS=json.dumps(list(assignment.allowed_tools)),
            PFC_RC7_DSH_SESSION_MODE='LEASE_BOUND_WORKER')
        prior = dict(self.env)
        self.env.update(projected)
        bound = ('RC72_RUNTIME_MISSION_CONTEXT=' + json.dumps(context, sort_keys=True)
            + '\nAll tools must use the registered native MCP tools. Include mission_context exactly as above. '
            'Use the original output_contract data_ref and precondition_refs as the only other arguments. '
            'Tool results are actual observations; do not report success when data or preconditions fail.\n' + prompt)
        try:
            return super().execute(assignment, bound)
        finally:
            self.env = prior
            try:
                gate.close()
            finally:
                self._native_gate, self._native_output = None, None

    def _tool_calls(self, events):
        calls = DshHeadlessWorkerLauncher._tool_calls(events)
        self._native_gate.verify_observed(calls)
        return calls

    def _final_json(self, events):
        output = DshHeadlessWorkerLauncher._final_json(events)
        self._native_gate.verify_output(output)
        self._native_output = output
        return output

    def _emit(self, event_name, invocation, extra=None):
        if event_name == 'HANDOFF_RETURNED':
            self._native_gate.complete(invocation, self._native_output)
            extra = dict(extra or {}, native_tool_gate_id=self._native_gate.gate_id)
        return super()._emit(event_name, invocation, extra)
