"""Load the approved host capability module through one fixed typed contract.

As with RC7.1 execution environments, the module is a trusted local
integration. Existing Captain-owned ReleaseBatches require an explicit,
batch-aware host factory; generic legacy **kwargs cannot silently bypass R1
Captain identity after cold restart.
"""
import importlib
import inspect
import re

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_mission_factory import MissionHostBindings


def load_mission_bindings(module_name, *, truth, release_id, source_commit,
                          release_batch_id=None):
    if not isinstance(module_name, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module_name):
        raise ContractError('MISSION_BINDINGS_MODULE_NAME_INVALID')
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ContractError('MISSION_BINDINGS_LOAD_FAILED:' + type(exc).__name__) from None
    factory = getattr(module, 'create_mission_bindings', None)
    if not callable(factory):
        raise ContractError('MISSION_BINDINGS_FACTORY_REQUIRED')

    context = dict(truth=truth, release_id=release_id, source_commit=source_commit)
    if release_batch_id is not None:
        if not isinstance(release_batch_id, str) or not release_batch_id.strip():
            raise ContractError('MISSION_BINDINGS_RELEASE_BATCH_REQUIRED')
        batches = truth.query('rc72_release_batch', release_batch_id=release_batch_id)
        if len(batches) != 1 or batches[0]['release_id'] != release_id:
            raise ContractError('MISSION_BINDINGS_CANONICAL_BATCH_REQUIRED')
        # A confirmed Captain lease is R1 truth; it cannot be downgraded by
        # a legacy factory which cannot even name the exact Mission/Batch.
        from rc7_runtime.rc72_captain_dispatch_fencing import install_captain_dispatch_overlay
        install_captain_dispatch_overlay()
        governed = bool(truth.query('rc72_captain_dispatch_lease',
                                    mission_id=batches[0]['mission_id']))
        try:
            params = inspect.signature(factory).parameters
        except (TypeError, ValueError):
            raise ContractError('MISSION_BINDINGS_EXPLICIT_FACTORY_SIGNATURE_REQUIRED') from None
        if governed and 'release_batch_id' not in params:
            raise ContractError('MISSION_BINDINGS_CAPTAIN_BATCH_AWARE_FACTORY_REQUIRED')
        if 'release_batch_id' in params:
            context['release_batch_id'] = release_batch_id
    try:
        bindings = factory(**context)
    except Exception as exc:
        # Even a host ContractError may contain private configuration values.
        raise ContractError('MISSION_BINDINGS_LOAD_FAILED:' + type(exc).__name__) from None
    if type(bindings) is not MissionHostBindings:
        raise ContractError('MISSION_BINDINGS_TYPED_CAPABILITIES_REQUIRED')
    if release_batch_id is not None:
        # Existing Captain missions need a real typed positive Host binding,
        # not a successful loader with silently absent ownership.
        if governed and bindings.captain_binding is None:
            raise ContractError('MISSION_BINDINGS_CAPTAIN_HOST_BINDING_REQUIRED')
    return bindings
