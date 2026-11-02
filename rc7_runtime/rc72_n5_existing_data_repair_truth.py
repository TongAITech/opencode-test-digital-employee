"""Independent projection for exact-DataRef repair admission records."""
from copy import deepcopy
from rc6_runtime import contracts, truth as registry

_KIND = 'rc72_n5_existing_data_repair'
_EVENT = 'RC72_N5_EXISTING_DATA_REPAIR_UPSERTED'
_SCHEMA = 'RC72_N5_EXISTING_DATA_REVERIFICATION_V1'
_FINAL = {'VERIFIED', 'REPAIR_REQUIRED'}


def _validate(payload):
    row = deepcopy(payload)
    for key in ('repair_id', 'release_id', 'source_commit', 'mission_id', 'release_batch_id',
                'preparation_id', 'boundary_id', 'data_requirement_id', 'verification_attempt_id', 'workitem_id', 'workitem_role',
                'mission_node_id', 'case_id', 'requirement_id', 'sst_id', 'obligation_id', 'source_case_sha256', 'signature'):
        contracts._require_str(row, key)
    if row.get('state') not in {'REQUESTED', 'DISPATCHING', 'OBSERVED'} | _FINAL:
        raise contracts.DomainValidationError('N5_EXISTING_REPAIR_STATE_INVALID')
    for key in ('original_binding', 'requirement', 'resource'):
        if not isinstance(row.get(key), dict):
            raise contracts.DomainValidationError('N5_EXISTING_REPAIR_CONTEXT_REQUIRED')
    contracts._require_string_list(row, 'allowed_tools')
    if not row['allowed_tools'] or any('*' in tool for tool in row['allowed_tools']):
        raise contracts.DomainValidationError('N5_EXISTING_REPAIR_SCOPED_TOOLS_REQUIRED')
    for key in ('node_pass', 'field_verified', 'bank_final', 'n6_ready', 'data_lease_id'):
        if key in row:
            raise contracts.DomainValidationError('N5_EXISTING_REPAIR_PREMATURE_CLAIM')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_n5_existing_data_repair_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'repair_id')
    registry.IDENTITY_FIELDS[_KIND] = 'repair_id'
    registry.BUCKETS[_KIND] = 'rc72_n5_existing_data_repairs'



install_rc72_n5_existing_data_repair_overlay()
