"""Load the approved host capability module through one fixed typed contract.

As with the RC7.1 execution environment, the operator-installed module is a
trusted local integration, not an untrusted proof document. It cannot replace
the native driver or return node success through this interface.
"""
import importlib
import re

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_mission_factory import MissionHostBindings


def load_mission_bindings(module_name, *, truth, release_id, source_commit):
    if not isinstance(module_name, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module_name):
        raise ContractError('MISSION_BINDINGS_MODULE_NAME_INVALID')
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ContractError('MISSION_BINDINGS_LOAD_FAILED:' + type(exc).__name__) from None
    factory = getattr(module, 'create_mission_bindings', None)
    if not callable(factory):
        raise ContractError('MISSION_BINDINGS_FACTORY_REQUIRED')
    try:
        bindings = factory(truth=truth, release_id=release_id, source_commit=source_commit)
    except Exception as exc:
        # Even a host ContractError may contain private configuration values.
        raise ContractError('MISSION_BINDINGS_LOAD_FAILED:' + type(exc).__name__) from None
    if type(bindings) is not MissionHostBindings:
        raise ContractError('MISSION_BINDINGS_TYPED_CAPABILITIES_REQUIRED')
    return bindings
