"""Structural comparison for an independent runtime batch mapping descriptor."""

from typing import NamedTuple

from .mission_scope_binding_codec import BindingStructureError, ScopeIdentity, serialize_scope


class RuntimeBatchMapping(NamedTuple):
    schema_version: int
    formal_authority_ref: str
    mapping_ref: str
    project_id: str
    batch_id: str
    runtime_release_id: str
    runtime_release_batch_id: str
    mission_id: str
    creation_operation_ref: str


def parse_runtime_batch_mapping(descriptor, scope):
    """Check decoded data against compact Scope without consulting any authority."""
    fields = RuntimeBatchMapping._fields
    if (type(descriptor) is not dict or any(type(key) is not str for key in descriptor)
            or descriptor.keys() != set(fields)):
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_INVALID')
    version = descriptor['schema_version']
    if type(version) is not int:
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_INVALID')
    if version != 1:
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_UNSUPPORTED')
    for field in fields[1:]:
        value = descriptor[field]
        if type(value) is not str or not value.strip():
            raise BindingStructureError('RUNTIME_BATCH_MAPPING_INVALID')
        try:
            value.encode('utf-8', 'strict')
        except UnicodeError:
            raise BindingStructureError('RUNTIME_BATCH_MAPPING_INVALID') from None

    if type(scope) is not ScopeIdentity or type(scope.classification) is not str:
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_REQUIRES_BOUND_SCOPE')
    fragment = serialize_scope(scope)
    if not fragment:
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_REQUIRES_BOUND_SCOPE')
    binding = fragment['scope_binding']
    mapping = binding['mapping']
    expected = {
        'schema_version': mapping['schema_version'],
        'formal_authority_ref': mapping['formal_authority_ref'],
        'mapping_ref': mapping['mapping_ref'],
        'project_id': binding['project_id'],
        'batch_id': binding['batch_id'],
        'runtime_release_id': mapping['runtime_release_id'],
        'mission_id': binding['mission_id'],
        'creation_operation_ref': binding['creation_operation_ref'],
    }
    if any(descriptor[field] != value for field, value in expected.items()):
        raise BindingStructureError('RUNTIME_BATCH_MAPPING_CONFLICT')
    return RuntimeBatchMapping(**descriptor)
