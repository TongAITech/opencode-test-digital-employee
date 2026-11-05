"""Captain-fenced admission of a real N9 professional qualification WorkItem.

This is deliberately NOT defect confirmation, reproduction or DSH success.
The original failed N7 Attempt, frozen Oracle and signed independent N8 gate
are re-verified by NativeN9ProfessionalIntakeService.  The only new authority
is one narrowly scoped, one-time professional WorkItem lease and a Fresh Worker
session; no business execution authority or product-defect verdict is issued.

The normal C07 dispatch_etu API must never be extended to let a N9 analyst
run a blocked N7 ETU's business operation.
"""
from __future__ import annotations

import time

from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_captain_scheduling import (
    CaptainFencedWorkItemScheduler, _ADMISSION_EVENT, _ADMITTED,
)
from .rc72_n9_professional_intake import NativeN9ProfessionalIntakeService
from .rc72_n7_pipeline import N7PipelineService
from .rc72_n7_execution_admission import _hash
from .rc72_domain import AutonomousMissionNode


class NativeN9CaptainQualificationAdmission:
    ROLE = 'N9_QUALIFY'
    CAPABILITY = 'defect_analysis'

    def __init__(self, pipeline: N7PipelineService):
        if not isinstance(pipeline, N7PipelineService):
            raise ContractError('N9_CAPTAIN_NATIVE_PIPELINE_REQUIRED')
        scheduler = pipeline.captain_scheduler
        if (not isinstance(scheduler, CaptainFencedWorkItemScheduler)
                or scheduler.truth is not pipeline.truth
                or scheduler.release_id != pipeline.release_id):
            raise ContractError('N9_CAPTAIN_NATIVE_SCHEDULER_REQUIRED')
        if not all((pipeline.captain_session_id, pipeline.captain_lease_id, pipeline.team_id)):
            raise ContractError('N9_CAPTAIN_EXPLICIT_IDENTITY_REQUIRED')
        self.pipeline, self.scheduler, self.truth = pipeline, scheduler, pipeline.truth
        self.intake = NativeN9ProfessionalIntakeService(pipeline)

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('N9_CAPTAIN_R1_NOT_UNIQUE:' + kind)
        return rows[0]

    def admit(self, *, preparation_id, diagnosis_id):
        # Can create only the original governed N9 WorkItem; never infer or
        # manufacture a PRODUCT_DEFECT from VALID_TEST_FAILURE.
        queued = self.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id)
        p = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
        wid = queued['qualification_workitem_id']
        plan = self._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
        members = [item for item in plan['items']
                   if item['workitem_id'] == p['workitem_id']
                   and item['case_id'] == p['case_id']
                   and item['contract_id'] == p['contract_id']]
        if len(members) != 1:
            raise ContractError('N9_CAPTAIN_ORIGINAL_CASE_ETU_NOT_UNIQUE')
        etu_id = members[0]['etu_id']
        with ledger_lock(self.truth, busy='N9_CAPTAIN_QUALIFICATION_LEDGER_BUSY'):
            # The original intake calls failure_evidence.audit(), which
            # acquires its own OS lock. Do not call it recursively here:
            # Windows byte-range locks are not reentrant. Under our existing
            # lock, use the evidence auditor's _audit_locked primitive and
            # recheck the signed N8 process, accepted R1 gate and original gap.
            failure = self.pipeline.failure_evidence._audit_locked(preparation_id)
            receipt = self.pipeline.diagnosis._verify(
                self._one('rc72_n8_process_diagnosis', diagnosis_id=diagnosis_id))
            outcome = self._one('rc72_diagnosis_outcome', diagnosis_id=diagnosis_id)
            gate_id = 'N8GATE-' + _hash([diagnosis_id, receipt['input_sha256']])[:24]
            gate = self._one('rc72_node_gate', gate_id=gate_id)
            n8 = self.pipeline.diagnosis.runtime.node_by_type(
                p['mission_id'], AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
            if (receipt['preparation_id'] != preparation_id
                    or receipt['source_commit'] != self.pipeline.source_commit
                    or receipt['release_id'] != self.pipeline.release_id
                    or receipt['result'].get('failure_class') != 'VALID_TEST_FAILURE'
                    or receipt['result'].get('confidence') != 'COMPLETE_FROZEN_CONTRACT_DISCREPANCY'
                    or receipt['result'].get('affected_refs') != [p['case_id']]
                    or outcome['source_attempt_id'] != p['attempt_id']
                    or outcome['responsible_node'] != 'N9_DEFECT'
                    or outcome.get('source_delivery_id') != receipt['delivery_id']
                    or outcome['gap_id'] != queued['gap_id']
                    or failure['evidence_id'] not in outcome['evidence_refs']
                    or n8['state'] != 'PASS' or gate_id not in n8['gate_refs']
                    or gate['decision'] != 'PASS'
                    or gate['delivery_id'] != receipt['delivery_id']
                    or gate['reviewer_worker_id'] != receipt['reviewer_worker_id']
                    or gate['reviewer_session_id'] != receipt['reviewer_session_id']
                    or failure['evidence_id'] not in gate['evidence_refs']):
                raise ContractError('N9_CAPTAIN_ACCEPTED_DIAGNOSIS_CHANGED')
            fencer = self.scheduler.fencer
            owner = fencer._owner(
                p['mission_id'], self.pipeline.captain_lease_id,
                self.pipeline.captain_session_id, int(time.time()))
            if (owner['team_id'] != self.pipeline.team_id
                    or owner['mission_id'] != p['mission_id']):
                raise ContractError('N9_CAPTAIN_TEAM_SCOPE_CHANGED')
            role_caps = self.scheduler.role_profiles.get(self.ROLE)
            # N9 analysis is not a second business request.  A richer
            # read-only skill policy can be admitted in a separate contract,
            # but not by silently copying N7's API / browser authority.
            if role_caps != frozenset((self.CAPABILITY,)):
                raise ContractError('N9_CAPTAIN_ANALYSIS_ONLY_PROFILE_REQUIRED')
            task = self._one('rc7_task', task_id=wid)
            if (task['mission_id'] != p['mission_id']
                    or task['node'] != 'DEFECT'
                    or task['task_type'] != 'N9_DISCREPANCY_QUALIFICATION'
                    or task['required_capabilities'] != [self.CAPABILITY]
                    or task['gap_refs'] != [queued['gap_id']]):
                raise ContractError('N9_CAPTAIN_QUALIFICATION_SCOPE_CHANGED')
            if not self.scheduler.scheduler._inputs_valid(task['input_artifact_refs']):
                raise ContractError('N9_CAPTAIN_ORIGINAL_INPUTS_INVALID')
            if not task['input_artifact_refs'] or any(
                    len(self.truth.query('rc7_artifact', artifact_id=ref)) != 1
                    or self._one('rc7_artifact', artifact_id=ref)['mission_id'] != p['mission_id']
                    for ref in task['input_artifact_refs']):
                raise ContractError('N9_CAPTAIN_ORIGINAL_INPUTS_CROSS_MISSION')
            etu = self._one('rc72_etu', etu_id=etu_id)
            if (etu['mission_id'] != p['mission_id']
                    or etu['release_batch_id'] != p['release_batch_id']
                    or p['case_id'] not in etu['case_ids']):
                raise ContractError('N9_CAPTAIN_ORIGINAL_ETU_CHANGED')
            # Existing admission is evidence of prior lease, not permission
            # to call DSH again, even after a cold controller restart.
            admissions = self.truth.query('rc72_captain_etu_admission', workitem_id=wid)
            if len(admissions) > 1:
                raise ContractError('N9_CAPTAIN_MULTIPLE_ADMISSIONS_FORBIDDEN')
            if admissions:
                prior = admissions[0]
                session = self._one('rc72_worker_session', session_id=prior['session_id'])
                if (prior['mission_id'] != p['mission_id']
                        or prior['team_id'] != self.pipeline.team_id
                        or prior['role'] != self.ROLE or prior['etu_id'] != etu_id
                        or prior['captain_lease_id'] != owner['lease_id']
                        or prior['captain_generation'] != owner['generation']
                        or prior['captain_session_id'] != owner['captain_session_id']
                        or prior['state'] != _ADMITTED
                        or session['worker_id'] != prior['worker_id']
                        or session['workitem_id'] != wid
                        or task['lease_owner'] != prior['worker_id']
                        or task['state'] not in ('LEASED', 'RUNNING', 'OUTPUT_PRODUCED')):
                    raise ContractError('N9_CAPTAIN_EXISTING_ADMISSION_SCOPE_CHANGED')
                return dict(status='HOLD', reason='N9_CAPTAIN_ALREADY_ADMITTED_NO_REPLAY',
                            qualification_workitem_id=wid,
                            qualification_admission_id=prior['admission_id'],
                            worker_id=prior['worker_id'], session_id=prior['session_id'],
                            defect_confirmed=False, reproduction_completed=False)
            # An orphan in the crash gap between Session and TaskLease is a
            # recovery incident, never a reason to allocate a second Worker.
            if self.truth.query('rc72_worker_session', mission_id=p['mission_id'],
                                workitem_id=wid):
                raise ContractError('N9_CAPTAIN_ORPHAN_RECONCILIATION_REQUIRED')
            if task['state'] == 'REGISTERED':
                self.scheduler.scheduler.refresh_ready(p['mission_id'])
                task = self._one('rc7_task', task_id=wid)
            if task['state'] != 'READY' or task.get('lease_owner'):
                raise ContractError('N9_CAPTAIN_QUALIFICATION_NOT_READY')
            # No direct N7 execution.  The ETU ref is read-only provenance for
            # the original blocked Case, not an executable ETU admission.
            fresh = self.scheduler.lifecycle.assign_fresh_worker(
                mission_id=p['mission_id'], team_id=self.pipeline.team_id,
                role=self.ROLE, etu_id=etu_id, workitem_id=wid,
                canonical_refs={
                    'etu_refs': [etu_id],
                    'executable_contract_refs': [p['contract_id']],
                    'gap_refs': [queued['gap_id']],
                    'evidence_refs': [failure['evidence_id']],
                })
            leased = self.scheduler.scheduler.lease_task(
                p['mission_id'], wid, worker_ref=fresh.worker_id,
                capabilities=role_caps)
            if leased is None or leased.lease_owner != fresh.worker_id:
                raise ContractError('N9_CAPTAIN_PARTIAL_LEASE_RECONCILIATION_REQUIRED')
            import uuid
            admission_id = 'CAPN9-' + uuid.uuid4().hex
            self.truth.append_atomic(_ADMISSION_EVENT, dict(
                admission_id=admission_id, release_id=self.pipeline.release_id,
                mission_id=p['mission_id'], team_id=self.pipeline.team_id,
                captain_lease_id=owner['lease_id'],
                captain_session_id=owner['captain_session_id'],
                captain_generation=owner['generation'], etu_id=etu_id,
                workitem_id=wid, role=self.ROLE,
                worker_id=fresh.worker_id, session_id=fresh.session_id,
                state=_ADMITTED, artifact_version=1))
            return dict(status='HOLD',
                        reason='N9_CAPTAIN_QUALIFICATION_AWAITS_SIGNED_DSH',
                        qualification_workitem_id=wid,
                        qualification_admission_id=admission_id,
                        worker_id=fresh.worker_id, session_id=fresh.session_id,
                        defect_confirmed=False, reproduction_completed=False)
