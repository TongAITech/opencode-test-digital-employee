"""Durable schema and read-only admission for unchanged-Case retry plans."""
from copy import deepcopy
import hmac
from rc6_runtime import contracts, truth as registry
from .models import ContractError

_KIND = 'rc72_n8_retry_reconciliation'
_EVENT = 'RC72_N8_RETRY_RECONCILIATION_UPSERTED'
_PURPOSE = 'N8_UNCHANGED_CASE_RETRY_RECONCILIATION'


def _validate(payload):
    row = deepcopy(payload)
    for key in ('reconciliation_id', 'release_id', 'source_commit', 'mission_id', 'release_batch_id',
                'preparation_id', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != _PURPOSE or row.get('state') not in {'PLANNED', 'READY'}:
        raise contracts.DomainValidationError('N8_RETRY_RECONCILIATION_STATE_INVALID')
    for key in ('original_plan', 'original_snapshot', 'original_preparation', 'original_binding', 'repair_record', 'boundary_record', 'n5_context'):
        if not isinstance(row.get(key), dict):
            raise contracts.DomainValidationError('N8_RETRY_RECONCILIATION_CONTEXT_REQUIRED')
    if not isinstance(row.get('members', []), list) or any(not isinstance(member, dict) for member in row.get('members', [])):
        raise contracts.DomainValidationError('N8_RETRY_MEMBER_CHECKPOINTS_REQUIRED')
    if row['state'] == 'READY' and not isinstance(row.get('member_decisions', []), list):
        raise contracts.DomainValidationError('N8_RETRY_MEMBER_DECISIONS_REQUIRED')
    if not isinstance(row.get('targets'), list):
        raise contracts.DomainValidationError('N8_RETRY_RECONCILIATION_TARGETS_REQUIRED')
    if row['state'] == 'READY' and not isinstance(row.get('plan'), dict):
        raise contracts.DomainValidationError('N8_RETRY_RECONCILIATION_PLAN_REQUIRED')
    for key in ('field_verified', 'bank_final', 'case_pass', 'execution_result'):
        if key in row:
            raise contracts.DomainValidationError('N8_RETRY_RECONCILIATION_PREMATURE_CLAIM')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_n8_retry_truth_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'reconciliation_id')
    registry.IDENTITY_FIELDS[_KIND] = 'reconciliation_id'
    registry.BUCKETS[_KIND] = 'rc72_n8_retry_reconciliations'


def verify_record(authority, row):
    if authority is None:
        raise ContractError('N8_RETRY_SIGNED_RUNTIME_AUTHORITY_REQUIRED')
    signed = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], authority._sign(signed)):
        raise ContractError('N8_RETRY_RECONCILIATION_SIGNATURE_INVALID')
    return row


def verify_reconciled_history(planning, plan):
    """Authenticate immutable past plan identity; grant no current permission."""
    from .rc72_n7_execution_admission import _hash
    row = verify_record(planning.authority,
        planning._one(_KIND, reconciliation_id=plan['recovery_id']))
    payload = {key: value for key, value in plan.items() if key != 'artifact_type'}
    if (row['state'] != 'READY' or row['purpose'] != _PURPOSE or row.get('plan') != payload
            or row['release_id'] != planning.release_id or row['source_commit'] != planning.source_commit
            or plan['mission_id'] != row['mission_id'] or plan['release_batch_id'] != row['release_batch_id']
            or plan['snapshot_id'] != row['original_snapshot']['snapshot_id']
            or plan['plan_id'] != 'N7REPLAN-' + _hash([row['reconciliation_id'], plan['input_digest']])[:24]):
        raise ContractError('N8_RETRY_PLAN_RECONCILIATION_MISMATCH')
    old = row['original_plan']
    if (planning._one('rc72_n7_execution_plan', plan_id=old['plan_id']) != old
            or planning._one('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id']) != row['original_snapshot']
            or planning._one('rc72_n7_execution_preparation', preparation_id=row['preparation_id']) != row['original_preparation']
            or planning._one('rc72_diagnosis_repair', diagnosis_id=row['repair_record']['diagnosis_id']) != row['repair_record']
            or planning._one('rc72_n8_repair_boundary', preparation_id=row['preparation_id']) != row['boundary_record']
            or planning._one('rc72_workitem_attempt_binding', binding_id=row['original_binding']['binding_id']) != row['original_binding']):
        raise ContractError('N8_RETRY_RECORDED_LINEAGE_CHANGED')
    old_items = {item['case_id']: item for item in old['items']}
    if {item['case_id'] for item in plan['items']} != set(old_items):
        raise ContractError('N8_RETRY_CASE_DENOMINATOR_CHANGED')
    for item in plan['items']:
        if any(item[key] != old_items[item['case_id']][key] for key in ('workitem_id', 'etu_id', 'input_artifact_refs')):
            raise ContractError('N8_RETRY_ORIGINAL_IDENTITY_REQUIRED')
    # Content-addressed admissions/contracts cannot silently acquire a different
    # historical payload just because the enclosing plan remains signed.
    from .rc72_n6_completion import _digest, _stable_id
    for item in plan['items']:
        admission = planning._one('rc72_n7_execution_admission', admission_id=item['admission_id'])
        payload = {k: v for k, v in admission.items() if k not in {'admission_id', 'status', 'artifact_type', 'artifact_version'}}
        contract = planning._one('rc72_n6_executable_contract', contract_id=item['contract_id'])
        if (admission['admission_id'] != 'N7ADM-' + _hash(payload)[:24] or admission['status'] != 'ADMITTED'
                or any(admission[k] != plan[k] for k in ('release_id', 'source_commit', 'mission_id', 'release_batch_id'))
                or admission['case_id'] != item['case_id'] or admission['contract_id'] != item['contract_id']
                or any(contract[k] != plan[k] for k in ('release_id', 'source_commit', 'mission_id', 'release_batch_id'))
                or contract['case_id'] != item['case_id']
                or any(admission[k] != contract[k] for k in ('requirement_id', 'sst_id', 'obligation_id'))
                or _digest(contract) != contract['contract_sha256']
                or contract['contract_id'] != _stable_id('N6CONTRACT', contract['mission_id'], contract['case_id'], contract['contract_sha256'])):
            raise ContractError('N8_RETRY_HISTORICAL_ADMISSION_OR_CONTRACT_CHANGED')
    return row


def assert_reconciled_plan(planning, plan):
    """Authenticate past identity AND current governed member dispositions."""
    row = verify_reconciled_history(planning, plan)
    from .rc72_n8_member_reuse import member_reuse_decisions
    if row.get('member_decisions', []) != member_reuse_decisions(planning, row, plan):
        raise ContractError('N8_REUSE_DECISION_CHANGED')
    from .rc72_n8_member_disposition import assert_member_projections
    assert_member_projections(planning, row)
    return row


install_rc72_n8_retry_truth_overlay()
