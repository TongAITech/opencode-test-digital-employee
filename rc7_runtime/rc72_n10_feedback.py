"""Structured N10 triage derived from the *persisted* release convergence snapshot.

A blocker is not a proven causal diagnosis. The responsible node here is a
review/disposition queue; unknown cases deliberately go to independent N8.
No caller-supplied percentages, invented obligations or synthetic evidence.
This read-only projection never marks a Gap resolved or creates a Node Gate.
"""
from .models import ContractError
from .rc72_domain import AutonomousMissionNode
from .rc72_release_convergence import ReleaseConvergenceSnapshot


class NativeN10FeedbackService:
    def __init__(self, truth, *, release_id):
        self.truth, self.release_id = truth, release_id

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('N10_FEEDBACK_R1_NOT_UNIQUE:' + kind)
        return rows[0]

    def derive(self, *, snapshot):
        if not isinstance(snapshot, ReleaseConvergenceSnapshot):
            raise ContractError('N10_FEEDBACK_NATIVE_SNAPSHOT_REQUIRED')
        batch = self._one('rc72_release_batch', release_batch_id=snapshot.release_batch_id)
        if batch['release_id'] != self.release_id or batch['mission_id'] != snapshot.mission_id:
            raise ContractError('N10_FEEDBACK_RELEASE_SCOPE_CHANGED')
        saved = self._one('rc72_release_convergence_snapshot', snapshot_id=snapshot.snapshot_id)
        if (saved['release_id'] != self.release_id or saved['release_batch_id'] != snapshot.release_batch_id
                or saved['mission_id'] != snapshot.mission_id or saved['result'] != snapshot.result.value
                or saved['blockers'] != snapshot.blockers):
            raise ContractError('N10_FEEDBACK_SNAPSHOT_CHANGED')
        manifest = self._one('rc72_release_scope_manifest', manifest_id=snapshot.manifest_id)
        if manifest['mission_id'] != snapshot.mission_id or manifest['release_batch_id'] != snapshot.release_batch_id:
            raise ContractError('N10_FEEDBACK_MANIFEST_SCOPE_CHANGED')

        known_nodes = {node.value for node in AutonomousMissionNode.ordered()}
        root = 'release-batch://' + snapshot.release_batch_id
        base_evidence = ['r1://artifact/' + snapshot.snapshot_id]
        issues = []
        for blocker in snapshot.blockers:
            issue = dict(blocker=blocker, gap_reason='CAUSE_NOT_PROVEN',
                responsible_node='N8_DIAGNOSIS_RECOVERY', scope_refs=[root],
                priority='P1', evidence_refs=list(base_evidence))
            if blocker.startswith('scope:missing-level:'):
                suffix = blocker[len('scope:missing-level:'):]
                sst, sep, level = suffix.rpartition(':')
                if not sep or level not in manifest['required_levels_by_sst'].get(sst, []):
                    raise ContractError('N10_FEEDBACK_REQUIRED_LEVEL_CHANGED')
                issue.update(gap_reason='REQUIRED_TEST_LEVEL_MISSING', responsible_node='N4_TEST_DESIGN',
                    scope_refs=[root, 'sst://' + sst, 'test-level://' + level], priority='P0',
                    evidence_refs=base_evidence + ['r1://artifact/' + snapshot.scope_snapshot_id,
                        'r1://artifact/' + snapshot.manifest_id])
            elif blocker.startswith('scope:missing-sst:'):
                sst = blocker[len('scope:missing-sst:'):]
                if sst not in {s for items in manifest['requirement_ssts'].values() for s in items}:
                    raise ContractError('N10_FEEDBACK_SST_SCOPE_CHANGED')
                issue.update(gap_reason='REQUIRED_SST_MISSING', responsible_node='N2_REQUIREMENT',
                    scope_refs=[root, 'sst://' + sst], priority='P0',
                    evidence_refs=base_evidence + ['r1://artifact/' + snapshot.manifest_id])
            elif blocker.startswith('coverage-gap:'):
                gap_id = blocker[len('coverage-gap:'):]
                gap = self._one('rc72_coverage_gap', gap_id=gap_id)
                if gap['mission_id'] != snapshot.mission_id or gap['release_batch_id'] != snapshot.release_batch_id:
                    raise ContractError('N10_FEEDBACK_COVERAGE_GAP_SCOPE_CHANGED')
                assigned = [n for n in gap.get('responsible_nodes', []) if n in known_nodes]
                issue.update(gap_reason=gap.get('gap_reason') or 'COVERAGE_CAUSE_UNKNOWN',
                    responsible_node=assigned[0] if len(assigned) == 1 else 'N8_DIAGNOSIS_RECOVERY',
                    scope_refs=[root] + [kind + '://' + gap[key] for kind, key in
                        (('requirement', 'requirement_id'), ('sst', 'sst_id'), ('obligation', 'obligation_id'))
                        if gap.get(key)], priority='P0' if gap.get('status') == 'AMBIGUOUS' else 'P1',
                    evidence_refs=base_evidence + list(gap.get('evidence_refs', [])) + ['r1://artifact/' + gap_id])
            elif blocker.startswith('obligation:') and blocker.endswith(':UNPROVEN'):
                obligation_id = blocker[len('obligation:'):-len(':UNPROVEN')]
                obligation = self._one('rc72_test_obligation', obligation_id=obligation_id)
                if obligation['mission_id'] != snapshot.mission_id or obligation['release_batch_id'] != snapshot.release_batch_id:
                    raise ContractError('N10_FEEDBACK_OBLIGATION_SCOPE_CHANGED')
                issue.update(gap_reason='TEST_OBLIGATION_NOT_PROVEN',
                    scope_refs=[root, 'requirement://' + obligation['requirement_id'],
                        'sst://' + obligation['sst_id'], 'obligation://' + obligation_id],
                    priority='P0' if obligation.get('risk_level') in {'HIGH', 'CRITICAL', 'BLOCKER'} else 'P1',
                    evidence_refs=base_evidence + ['r1://artifact/' + obligation_id])
            elif blocker.startswith('defect:'):
                parts = blocker.split(':', 2)
                if len(parts) == 3:
                    defect = self._one('rc7_defect', defect_id=parts[1])
                    if defect['mission_id'] != snapshot.mission_id:
                        raise ContractError('N10_FEEDBACK_DEFECT_SCOPE_CHANGED')
                    issue.update(gap_reason='OPEN_PROFESSIONAL_DEFECT',
                        responsible_node='N9_DEFECT', scope_refs=[root, 'defect://' + parts[1]],
                        priority='P0' if defect.get('severity') in {'HIGH', 'CRITICAL', 'BLOCKER'} else 'P1',
                        evidence_refs=base_evidence + ['r1://artifact/' + parts[1]])
            elif blocker.startswith('node:'):
                parts = blocker.split(':', 2)
                if len(parts) == 3 and parts[1] in known_nodes:
                    issue.update(gap_reason='MISSION_NODE_NOT_ACCEPTED', responsible_node=parts[1],
                        scope_refs=[root, 'mission-node://' + parts[1]], priority='P0')
            elif blocker.startswith('workitem:'):
                parts = blocker.split(':', 2)
                if len(parts) == 3:
                    task = self._one('rc7_task', task_id=parts[1])
                    if task['mission_id'] != snapshot.mission_id:
                        raise ContractError('N10_FEEDBACK_WORKITEM_SCOPE_CHANGED')
                    queue = {'EXECUTION': 'N7_EXECUTION', 'TEST_DATA': 'N5_TEST_DATA',
                        'TEST_DESIGN': 'N4_TEST_DESIGN', 'CODE_ANALYSIS': 'N3_CODE_ANALYSIS',
                        'DIAGNOSIS': 'N8_DIAGNOSIS_RECOVERY', 'DEFECT': 'N9_DEFECT'}
                    issue.update(gap_reason='WORKITEM_NOT_ACCEPTED',
                        responsible_node=queue.get(task.get('node'), 'N8_DIAGNOSIS_RECOVERY'),
                        scope_refs=[root, 'workitem://' + parts[1]],
                        priority='P0' if parts[2] in {'BLOCKED', 'HUMAN_REQUIRED'} else 'P1',
                        evidence_refs=base_evidence + ['r1://artifact/' + parts[1]])
            issues.append(issue)
        return issues
