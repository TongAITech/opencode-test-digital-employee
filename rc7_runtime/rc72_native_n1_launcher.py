"""Native N1 DSH launcher with real parent-owned, input-scoped source reads."""
import json
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .rc72_native_n1_read_gate import NativeN1ReadGate


class NativeN1ReadDshLauncher(DshHeadlessWorkerLauncher):
    def __init__(self,*,resources,**kwargs):
        super().__init__(**kwargs)
        self.resources=tuple(resources)
        self.native_service=None;self._native_gate=None;self._native_output=None

    def bind_native_service(self,service):
        from .rc72_mission_node_handoff import N1DshHandoffService
        if (not isinstance(service,N1DshHandoffService) or service.truth is not self.truth
                or service.launcher is not self or self._native_gate is not None):
            raise ContractError('N1_NATIVE_READ_SERVICE_BINDING_INVALID')
        self.native_service=service

    def execute(self,assignment,prompt):
        if self.native_service is None or self._native_gate is not None:
            raise ContractError('N1_NATIVE_READ_SERVICE_REQUIRED')
        gate=NativeN1ReadGate(self.native_service,assignment,self.resources,capture_root=self.state_root/'native-input-captures')
        self._native_gate=gate;prior=dict(self.env)
        try:
            gate.open()
            context=dict(mission_id=gate.base['mission_id'],task_id=gate.base['workitem_id'],worker_id=gate.base['worker_id'])
            self.env.update(gate.environment(),PFC_RC7_MCP_MISSION_ID=context['mission_id'],PFC_RC7_MCP_TASK_ID=context['task_id'],
                PFC_RC7_MCP_WORKER_ID=context['worker_id'],PFC_RC7_MCP_LEASE_ID=assignment.lease.lease_id,
                PFC_RC7_MCP_SCOPE_REF=assignment.scope,PFC_RC7_DSH_ALLOWED_TOOLS=json.dumps(list(assignment.allowed_tools)),
                PFC_RC7_DSH_SESSION_MODE='LEASE_BOUND_WORKER')
            bound=('RC72_NATIVE_INPUT_READ_CONTEXT='+json.dumps(context,sort_keys=True)+'\n'
                'Use only the registered native input-read tool with source_ref from the original approved input_refs. '
                'Include mission_context exactly as above. Never substitute a filesystem path or invent tool observations.\n'+prompt)
            return super().execute(assignment,bound)
        finally:
            self.env=prior
            try:gate.close()
            finally:self._native_gate=None;self._native_output=None

    def _tool_calls(self,events):
        calls=super()._tool_calls(events)
        self._native_gate.observed(calls)
        return calls

    def _final_json(self,events):
        output=super()._final_json(events);self._native_output=output
        return output

    def _emit(self,event_name,invocation,extra=None):
        if event_name=='HANDOFF_RETURNED':
            self._native_gate.complete(invocation,self._native_output)
            extra=dict(extra or {},native_n1_read_gate_id=self._native_gate.gate_id)
        return super()._emit(event_name,invocation,extra)
