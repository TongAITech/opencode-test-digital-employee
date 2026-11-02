"""Read-only current-scope disposition for a drained execution member.

A current admission plus signed reconciliation can carry historical evidence to
whole-plan review. It cannot restore the old worker lease or produce a PASS.
"""
import hashlib
import hmac
from pathlib import Path

from .models import ContractError
from .rc72_n6_completion import _digest


def _strings(value):
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_strings(v) for v in value)) if value else set()
    return set()


def member_reuse_decisions(planning, reconciliation, plan):
    members = reconciliation.get('members', [])
    if not isinstance(members, list):
        raise ContractError('N8_REUSE_MEMBER_DENOMINATOR_INVALID')
    impact = planning._one('rc72_impact_set', impact_set_id=reconciliation['repair_record']['impact_set_id'])
    if members and reconciliation.get('impact_record') != impact:
        raise ContractError('N8_REUSE_RECORDED_IMPACT_CHANGED')
    items = {item['case_id']: item for item in plan['items']}
    seen, decisions = set(), []
    for member in members:
        signed = {k: v for k, v in member.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
        if not hmac.compare_digest(member['signature'], planning.authority._sign(signed)):
            raise ContractError('N8_REUSE_CHECKPOINT_SIGNATURE_INVALID')
        old = member['original_preparation']
        if (member['state'] != 'DRAINED' or old['case_id'] in seen
                or any(member[key] != plan[key] for key in ('mission_id', 'release_batch_id', 'release_id', 'source_commit'))
                or planning._one('rc72_n7_member_drain', drain_id=member['drain_id']) != member):
            raise ContractError('N8_REUSE_CHECKPOINT_SCOPE_CHANGED')
        inherited_reexecution = False
        if member['plan_id'] != reconciliation['original_plan']['plan_id']:
            from .rc72_n8_retry_truth import verify_reconciled_history
            parent = verify_reconciled_history(planning, reconciliation['original_plan'])
            inherited = [d for d in parent.get('member_decisions', []) if d['preparation_id'] == old['preparation_id']]
            if (member not in parent.get('members', []) or len(inherited) != 1
                    or inherited[0]['disposition'] not in {'REUSE_FOR_CURRENT_REVIEW', 'REEXECUTE_AFTER_VERIFIED_DRAIN'}):
                raise ContractError('N8_REUSE_INHERITED_MEMBER_PROOF_REQUIRED')
            # A mandatory re-execution is sticky until an actual fresh Attempt
            # produces new evidence. Later source equality cannot revive it.
            inherited_reexecution = inherited[0]['disposition'] == 'REEXECUTE_AFTER_VERIFIED_DRAIN'
        seen.add(old['case_id'])
        item = items.get(old['case_id'])
        if item is None or any(item[key] != old[key] for key in ('workitem_id', 'etu_id')):
            raise ContractError('N8_REUSE_ORIGINAL_MEMBER_IDENTITY_REQUIRED')
        previous = planning._one('rc72_n6_executable_contract', contract_id=old['contract_id'])
        current = planning._one('rc72_n6_executable_contract', contract_id=item['contract_id'])
        changed = set(reconciliation['repair_record']['changed_refs']) | set(impact['changed_refs'])
        # Data proof provenance and every business/runtime field are in this
        # digest. Merely keeping the same DataRef or non-STALE ETU is insufficient.
        if _digest(current) != current['contract_sha256'] or _digest(previous) != previous['contract_sha256']:
            raise ContractError('N8_MEMBER_CONTRACT_DIGEST_INVALID')
        unaffected = (not inherited_reexecution and impact['strategy'] == 'EXPLICIT_DEPENDENCY' and old['etu_id'] not in impact['stale_etu_ids']
                and previous['obligation_id'] not in impact['stale_obligation_ids']
                and not changed & _strings(previous) and current['contract_sha256'] == previous['contract_sha256'])
        disposition = 'REUSE_FOR_CURRENT_REVIEW' if unaffected else 'REEXECUTE_AFTER_VERIFIED_DRAIN'
        expected = dict(old, status='DRAINED', artifact_version=old['artifact_version'] + 1)
        actual = planning._one('rc72_n7_execution_preparation', preparation_id=old['preparation_id'])
        interrupted = dict(old, status='INTERRUPTED', artifact_version=old['artifact_version'] + 2)
        if actual != expected and (unaffected or actual != interrupted):
            raise ContractError('N8_REUSE_ORIGINAL_PREPARATION_CHANGED')
        original_admission = planning._one('rc72_n7_execution_admission', admission_id=old['admission_id'])
        admission = planning.admission.assert_review_current(item['admission_id'])
        required = {'N1_REALITY', 'N2_REQUIREMENT', 'N3_CODE_ANALYSIS', 'N4_TEST_DESIGN'}
        before = {p['node_type']: p for p in original_admission['upstream_refs'] if p['node_type'] in required}
        after = {p['node_type']: p for p in admission['upstream_refs'] if p['node_type'] in required}
        if set(before) != required or before != after:
            raise ContractError('N8_REUSE_UPSTREAM_SEMANTIC_REPAIR_REQUIRED')
        captures = member['captured_evidence']
        declarations = {entry['requirement']: entry for entry in member['case_snapshot']['evidence_declarations']}
        if len(captures) != len(declarations) or {entry['requirement'] for entry in captures} != set(declarations):
            raise ContractError('N8_REUSE_CAPTURE_DENOMINATOR_CHANGED')
        for entry in captures:
            ref = entry['content_ref']
            path = Path(ref[len('file://'):]) if ref.startswith('file://') else None
            if (path is None or path.is_symlink() or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']
                    or path.stat().st_size != entry['size_bytes']
                    or entry['sha256'] != declarations[entry['requirement']]['sha256']):
                raise ContractError('N8_REUSE_CAPTURE_BYTES_CHANGED')
        decisions.append(dict(case_id=old['case_id'], workitem_id=old['workitem_id'], etu_id=old['etu_id'],
            preparation_id=old['preparation_id'], attempt_id=old['attempt_id'], drain_id=member['drain_id'],
            disposition=disposition, current_contract_id=item['contract_id'],
            current_contract_sha256=current['contract_sha256'], current_admission_id=item['admission_id'],
            impact_set_id=impact['impact_set_id']))
    return decisions


def reused_member(preparation, plan, item, *, allow_finalized=False):
    if not plan.get('recovery_id'):
        return None
    from .rc72_n8_retry_truth import assert_reconciled_plan
    row = assert_reconciled_plan(preparation.planning, plan)
    if not any(d['workitem_id'] == item['workitem_id'] and d['disposition'] == 'REUSE_FOR_CURRENT_REVIEW'
               for d in row.get('member_decisions', [])):
        return None
    matches = [member for member in row.get('members', [])
               if member['original_preparation']['workitem_id'] == item['workitem_id']]
    if not matches:
        return None
    if len(matches) != 1:
        raise ContractError('N8_REUSE_MEMBER_NOT_UNIQUE')
    from .rc72_n7_member_drain import assert_drained_member
    member = assert_drained_member(preparation, matches[0]['preparation_id'], allow_finalized=allow_finalized)
    if member != matches[0]:
        raise ContractError('N8_REUSE_CHECKPOINT_CHANGED')
    return member
