"""Stage-one structural preservation and disposable R1 write boundaries."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import models, truth_overlay
from rc7_runtime.closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from rc7_runtime.mission_scope_preservation import (
    clone_mission, isolate_mission_scope, serialize_mission_scope,
)
from rc7_runtime.models import Mission, MissionStatus, to_payload
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_runtime.unadmitted_scope_guard import reject_reserved
from test_dsh_workbench_mission_scope_binding_codec import bound
from tools.dsh_workbench.mission_scope_binding_codec import BindingStructureError, parse_scope


ROOT = Path(__file__).resolve().parents[1]
HOLD = 'MISSION_SCOPE_NOT_ADMITTED'
GOLDEN_SHA256 = '204e86f036cc5c8ba3e67e5c45799a6fcf77d04625c5dbd00491618fc2f18c90'


def mission():
    return Mission('M1', 'RT1', 'goal', created_at=10, updated_at=11)


def tripwire(*args, **kwargs):
    pytest.fail('effect reached before Mission Scope rejection')


def snapshot(truth):
    return truth.store.path.read_bytes(), truth.projection.snapshot()


def test_legacy_constructor_wire_direct_append_and_cold_update(tmp_path):
    truth = TruthRuntime(tmp_path / 'r1')
    legacy = Mission(' M1 ', ' RT1 ', ' goal ', created_at=10, updated_at=11)
    expected = {
        'mission_id': 'M1', 'release_id': 'RT1', 'goal': 'goal', 'state': 'REGISTERED',
        'sufficiency_state': 'UNKNOWN', 'artifact_refs': [], 'open_gap_ids': [],
        'active_task_ids': [], 'residual_risk_ids': [], 'latest_evaluation_id': None,
        'revision': 1, 'created_at': 10, 'updated_at': 11,
    }
    assert '_scope_state' not in vars(legacy)
    assert to_payload(legacy) == expected
    assert to_payload(replace(legacy)) == expected
    assert to_payload(clone_mission(legacy)) == expected
    assert serialize_mission_scope(legacy) == {}
    truth_overlay.append_entity(truth, legacy, release_id='RT1')
    legacy.state = MissionStatus.RUNNING
    # Preserve legacy release override for a genuinely unbound target.
    truth_overlay.append_entity(truth, legacy, release_id=' RT2 ', artifact_version=2)
    row = TruthRuntime(truth.store.path).query('rc7_mission', mission_id='M1')[0]
    assert row['release_id'] == 'RT2' and row['state'] == 'RUNNING'
    assert not {'_scope_state', 'scope_binding', 'project_id', 'batch_id'}.intersection(row)


@pytest.mark.parametrize('attribute,value', [
    ('project_id', None), ('batch_id', ''), ('scope_binding', None),
    ('scope_binding', {'partial': True}), ('_scope_state', None),
    ('_scope_state', 'absent'), ('_scope_state', object()),
])
def test_generic_boundaries_hold_before_any_effect(tmp_path, monkeypatch, attribute, value):
    truth = TruthRuntime(tmp_path / 'r1')
    incoming = mission()
    setattr(incoming, attribute, value)
    before = snapshot(truth)
    monkeypatch.setattr(models, 'asdict', tripwire)
    monkeypatch.setattr(truth_overlay, '_enforce_durable_acceptance', tripwire)
    monkeypatch.setattr(truth, 'append_atomic', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(incoming)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, incoming, release_id='RT1')
    with pytest.raises(RuntimeError, match=HOLD):
        reject_reserved(incoming)
    assert snapshot(truth) == before


def test_complete_scope_stays_immutable_through_isolated_roundtrip(tmp_path, monkeypatch):
    truth = TruthRuntime(tmp_path / 'r1')
    payload = bound()
    value = isolate_mission_scope(mission(), payload)
    golden = parse_scope(payload).binding_bytes
    assert len(golden) == 709
    assert hashlib.sha256(golden).hexdigest() == GOLDEN_SHA256
    detached = serialize_mission_scope(value)
    assert detached['scope_binding'] == payload['scope_binding']
    payload['scope_binding']['binding_ref'] = 'changed'
    detached['scope_binding']['binding_ref'] = 'changed again'
    cloned = clone_mission(value)
    copied = deepcopy(value)
    assert cloned is not value and copied is not value
    for candidate in (value, cloned, copied):
        assert candidate._scope_state.binding_bytes == golden
        assert serialize_mission_scope(candidate)['scope_binding']['binding_ref'] == 'bind:1'
    # The standard replace API has no contract for this init=False state.
    assert replace(value)._scope_state is models._SCOPE_ABSENT
    with pytest.raises(AttributeError):
        value._scope_state.binding_bytes = b'changed'
    before = snapshot(truth)
    monkeypatch.setattr(models, 'asdict', tripwire)
    monkeypatch.setattr(truth_overlay, '_enforce_durable_acceptance', tripwire)
    monkeypatch.setattr(truth, 'append_atomic', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(value)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, value, release_id='OTHER')
    with pytest.raises(ClosedLoopControlError, match=HOLD):
        ClosedLoopControlPlane.bootstrap(truth, value)
    assert snapshot(truth) == before


@pytest.mark.parametrize('alteration,code', [
    ('null', 'BINDING_EXPLICIT_NULL'), ('partial', 'BINDING_STRUCTURE_INVALID'),
    ('flat', 'BINDING_FLAT_ONLY_UNQUALIFIED'), ('mirror', 'BINDING_MIRROR_CONFLICT'),
    ('mission_trim', 'BINDING_IDENTITY_CONFLICT'), ('release_trim', 'BINDING_IDENTITY_CONFLICT'),
])
def test_isolated_decoder_rejects_invalid_or_rewritten_scope(alteration, code):
    payload = bound()
    if alteration == 'null':
        payload['scope_binding'] = None
    elif alteration == 'partial':
        del payload['scope_binding']['snapshot_ref']
    elif alteration == 'flat':
        del payload['scope_binding']
    elif alteration == 'mirror':
        payload['project_id'] = 'wrong'
    elif alteration == 'mission_trim':
        payload['mission_id'] = payload['scope_binding']['mission_id'] = ' M1 '
    else:
        payload['release_id'] = payload['scope_binding']['mapping']['runtime_release_id'] = ' RT1 '
    with pytest.raises(BindingStructureError, match=code):
        isolate_mission_scope(mission(), payload)


def test_isolated_serializer_rejects_changed_identity_and_noncanonical_state():
    value = isolate_mission_scope(mission(), bound())
    value.release_id = 'OTHER'
    with pytest.raises(BindingStructureError, match='BINDING_IDENTITY_CONFLICT'):
        serialize_mission_scope(value)
    value = isolate_mission_scope(mission(), bound())
    state = value._scope_state
    value._scope_state = state._replace(binding_bytes=b' ' + state.binding_bytes)
    with pytest.raises(BindingStructureError, match='BINDING_STRUCTURE_INVALID'):
        clone_mission(value)


@pytest.mark.parametrize('key', ['project_id', 'batch_id', 'scope_binding'])
def test_direct_append_uses_canonical_global_target_before_acceptance(tmp_path, monkeypatch, key):
    truth = TruthRuntime(tmp_path / 'r1')
    truth_overlay.append_entity(truth, mission(), release_id='RT1')
    row = truth.query('rc7_mission', mission_id='M1')[0]
    row.update({key: None, 'artifact_version': 2})
    truth.append_atomic('RC7_MISSION_UPSERTED', row)
    before = snapshot(truth)
    incoming = Mission('M1', 'RT2', 'goal')
    incoming.mission_id = ' M1 '
    query = truth.query
    calls = []

    def read(kind, **filters):
        calls.append((kind, filters))
        return query(kind, **filters)

    monkeypatch.setattr(truth, 'query', read)
    monkeypatch.setattr(truth_overlay, '_enforce_durable_acceptance', tripwire)
    monkeypatch.setattr(truth, 'append_atomic', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, incoming, release_id='RT2', artifact_version=3)
    assert calls == [('rc7_mission', {'mission_id': 'M1'})]
    assert snapshot(truth) == before
    cold = TruthRuntime(truth.store.path)
    assert cold.query('rc7_mission', mission_id='M1')[0][key] is None
    assert snapshot(cold) == before


def test_direct_append_uses_one_detached_mission_snapshot(tmp_path, monkeypatch):
    truth = TruthRuntime(tmp_path / 'r1')
    incoming = mission()
    incoming.mission_id = ' M1 '
    incoming.artifact_refs = ['original-ref']
    query = truth.query
    calls = []

    def read(kind, **filters):
        calls.append((kind, filters))
        incoming.mission_id = 'M2'
        incoming.state = MissionStatus.CONVERGED
        incoming.artifact_refs.append('late-ref')
        return query(kind, **filters)

    monkeypatch.setattr(truth, 'query', read)
    monkeypatch.setattr(models, 'asdict', tripwire)
    receipt = truth_overlay.append_entity(truth, incoming, release_id='RT1')
    assert calls == [('rc7_mission', {'mission_id': 'M1'})]
    assert receipt.entity_id == 'M1'
    cold = TruthRuntime(truth.store.path)
    assert cold.query('rc7_mission', mission_id='M2') == []
    row = cold.query('rc7_mission', mission_id='M1')[0]
    assert row['artifact_refs'] == ['original-ref']
    assert row['state'] == 'REGISTERED'


@pytest.mark.parametrize('field_name,value', [
    ('mission_id', None), ('state', 'REGISTERED'), ('artifact_refs', [None]),
    ('revision', True), ('latest_evaluation_id', []),
])
def test_malformed_declared_mission_fields_reject_before_query(tmp_path, monkeypatch, field_name, value):
    truth = TruthRuntime(tmp_path / 'r1')
    incoming = mission()
    setattr(incoming, field_name, value)
    before = snapshot(truth)
    monkeypatch.setattr(truth, 'query', tripwire)
    monkeypatch.setattr(truth, 'append_atomic', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(incoming)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, incoming, release_id='RT1')
    assert snapshot(truth) == before


def test_direct_mission_serializer_never_copies_custom_identifier(tmp_path, monkeypatch):
    class CustomIdentifier(str):
        __deepcopy__ = tripwire

    truth = TruthRuntime(tmp_path / 'r1')
    incoming = mission()
    incoming.mission_id = CustomIdentifier('M1')
    before = snapshot(truth)
    monkeypatch.setattr(truth, 'query', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(incoming)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, incoming, release_id='RT1')
    assert snapshot(truth) == before


def test_legacy_derived_serializer_and_exact_writer_dispatch(tmp_path):
    @dataclass
    class Derived(Mission):
        note: str = 'legacy'

    value = Derived('M1', 'RT1', 'goal')
    assert to_payload(value)['note'] == 'legacy'
    assert '_scope_state' not in to_payload(value)
    truth = TruthRuntime(tmp_path / 'r1')
    before = truth.store.path.read_bytes()
    with pytest.raises(TypeError, match='UNSUPPORTED_RC7_ENTITY'):
        truth_overlay.append_entity(truth, value, release_id='RT1')
    with pytest.raises(TypeError, match='UNSUPPORTED_RC72_ENTITY'):
        append_rc72_entity(truth, mission(), release_id='RT1')
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('name', ['_scope_state', 'scope_binding', '__dict__'])
def test_derived_scope_descriptors_are_not_invoked(tmp_path, monkeypatch, name):
    kind = type('ExceptionalMission', (Mission,), {name: property(tripwire)})
    value = kind('M1', 'RT1', 'goal')
    truth = TruthRuntime(tmp_path / 'r1')
    monkeypatch.setattr(models, 'asdict', tripwire)
    monkeypatch.setattr(truth_overlay, '_enforce_durable_acceptance', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(value)
    with pytest.raises(ValueError, match=HOLD):
        truth_overlay.append_entity(truth, value, release_id='RT1')
    assert truth.store.path.read_bytes() == b''


def test_derived_reserved_dataclass_field_is_rejected_before_asdict(monkeypatch):
    @dataclass
    class DeclaredScope(Mission):
        scope_binding: object = field(init=False, default=None)

    value = DeclaredScope('M1', 'RT1', 'goal')
    assert 'scope_binding' not in vars(value)
    monkeypatch.setattr(models, 'asdict', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(value)


def test_workbench_codec_import_is_pure_in_new_process():
    script = """
import hashlib
import sys
sys.path.insert(0, sys.argv[1])
from tools.dsh_workbench import mission_scope_binding_codec as old
from dsh_scope_codec import mission_binding as leaf
assert not any(n.startswith(('rc7_runtime', 'rc6_runtime')) for n in sys.modules)
for name in old.__all__:
    assert getattr(old, name) is getattr(leaf, name)
parsed = old.parse_mission_json(sys.stdin.buffer.read())
assert len(parsed.scope.binding_bytes) == 709
print(hashlib.sha256(parsed.scope.binding_bytes).hexdigest())
"""
    result = subprocess.check_output([sys.executable, '-I', '-c', script, str(ROOT)],
                                     input=json.dumps(bound()).encode())
    assert result.decode().strip() == GOLDEN_SHA256


def test_offline_source_copy_contains_shared_leaf_and_runtime_imports(tmp_path):
    from rc7_release.package import REQUIRED_PRODUCT_FILES, SOURCE_DIRS, _copy_tree

    archive = tmp_path / 'source-copy'
    for name in SOURCE_DIRS:
        _copy_tree(ROOT / name, archive / name)
    for relative in ('dsh_scope_codec/__init__.py', 'dsh_scope_codec/mission_binding.py',
                     'rc7_runtime/mission_scope_preservation.py'):
        assert relative in REQUIRED_PRODUCT_FILES and (archive / relative).is_file()
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from dsh_scope_codec import mission_binding
from rc7_runtime.models import Mission, to_payload
from rc7_runtime.mission_scope_preservation import serialize_mission_scope
Path(mission_binding.__file__).relative_to(sys.argv[1])
mission = Mission('M', 'R', 'goal')
assert serialize_mission_scope(mission) == {}
assert 'scope_binding' not in to_payload(mission)
assert not any(n.startswith('tools.dsh_workbench') for n in sys.modules)
"""
    subprocess.check_call([sys.executable, '-I', '-c', script, str(archive)], cwd=tmp_path)


def test_cold_existing_compact_row_preserves_raw_scope_and_stays_held(tmp_path):
    truth = TruthRuntime(tmp_path / 'r1')
    row = dict(to_payload(mission()), **{k: v for k, v in bound().items()
                                        if k not in ('mission_id', 'release_id')})
    row['artifact_version'] = 1
    truth.append_atomic('RC7_MISSION_UPSERTED', row)
    before = snapshot(truth)
    cold = TruthRuntime(truth.store.path)
    raw = cold.query('rc7_mission', mission_id='M1')[0]
    isolated = isolate_mission_scope(mission(), raw)
    assert serialize_mission_scope(isolated)['scope_binding'] == row['scope_binding']
    with pytest.raises(ClosedLoopControlError, match=HOLD):
        ClosedLoopControlPlane(cold, 'RT1', 'M1')
    assert snapshot(cold) == before


def test_fake_absent_object_is_not_compared_or_probed(monkeypatch):
    class FakeAbsent:
        __eq__ = tripwire
        __getattr__ = tripwire
        __deepcopy__ = tripwire

    value = mission()
    value._scope_state = FakeAbsent()
    monkeypatch.setattr(models, 'asdict', tripwire)
    with pytest.raises(ValueError, match=HOLD):
        to_payload(value)
    with pytest.raises(ValueError, match=HOLD):
        clone_mission(value)


def test_scope_check_rejects_effective_getter_from_later_mixin():
    class GetterMixin:
        def __getattribute__(self, name):
            if name in ('_scope_state', '__dict__', 'scope_binding'):
                tripwire()
            return object.__getattribute__(self, name)

    class Exceptional(Mission, GetterMixin):
        pass

    with pytest.raises(ValueError, match=HOLD):
        to_payload(Exceptional('M1', 'RT1', 'goal'))


@pytest.mark.parametrize('hook', ['__deepcopy__', '__reduce__', '__reduce_ex__', '__getstate__', '__iter__'])
def test_bound_clone_rejects_instance_hooks_without_losing_scope(tmp_path, hook):
    truth = TruthRuntime(tmp_path / 'r1')
    value = isolate_mission_scope(mission(), bound())
    scope = value._scope_state
    before = snapshot(truth)
    calls = []

    def lose_scope(*args):
        calls.append(hook)
        return mission()

    setattr(value, hook, lose_scope)
    with pytest.raises(ValueError, match=HOLD):
        clone_mission(value)
    assert calls == [] and value._scope_state is scope
    assert snapshot(truth) == before


def test_isolate_rejects_instance_hook_that_substitutes_mission_identity(tmp_path):
    truth = TruthRuntime(tmp_path / 'r1')
    value = mission()
    before = snapshot(truth)
    calls = []

    def substitute(memo):
        calls.append('substitute')
        return Mission('OTHER', 'OTHER-RT', 'substitute')

    value.__deepcopy__ = substitute
    with pytest.raises(ValueError, match=HOLD):
        isolate_mission_scope(value, bound())
    assert calls == []
    assert value.mission_id == 'M1' and value.release_id == 'RT1'
    assert serialize_mission_scope(value) == {} and snapshot(truth) == before


@pytest.mark.parametrize('attribute', ['artifact_refs', 'open_gap_ids', 'active_task_ids', 'residual_risk_ids'])
def test_nested_string_subclass_cannot_change_a_reference_during_isolation(tmp_path, attribute):
    truth = TruthRuntime(tmp_path / 'r1')
    calls = []

    class NestedRef(str):
        def __deepcopy__(self, memo):
            calls.append('nested copy')
            return 'changed'

        __reduce__ = tripwire
        __reduce_ex__ = tripwire
        __getstate__ = tripwire
        __iter__ = tripwire

    value = mission()
    ref = NestedRef('reference')
    setattr(value, attribute, [ref])
    before = snapshot(truth)
    with pytest.raises(ValueError, match=HOLD):
        isolate_mission_scope(value, bound())
    assert calls == [] and getattr(value, attribute)[0] is ref
    assert snapshot(truth) == before


def test_clone_does_not_iterate_unknown_reference_container():
    class UnknownList(list):
        __iter__ = tripwire
        __deepcopy__ = tripwire
        __reduce__ = tripwire
        __reduce_ex__ = tripwire
        __getstate__ = tripwire

    value = mission()
    value.artifact_refs = UnknownList(['reference'])
    with pytest.raises(ValueError, match=HOLD):
        clone_mission(value)


def test_clone_does_not_probe_unknown_scalar():
    class UnknownScalar:
        __getattribute__ = tripwire
        __deepcopy__ = tripwire
        __reduce__ = tripwire
        __reduce_ex__ = tripwire
        __getstate__ = tripwire
        __iter__ = tripwire

    value = mission()
    value.goal = UnknownScalar()
    with pytest.raises(ValueError, match=HOLD):
        clone_mission(value)


def test_clone_keeps_all_declared_values_and_detaches_reference_lists():
    from dataclasses import fields

    base = mission()
    base.state = MissionStatus.RUNNING
    base.goal = ' preserve existing text '
    base.latest_evaluation_id = 'E1'
    reference_fields = ('artifact_refs', 'open_gap_ids', 'active_task_ids', 'residual_risk_ids')
    for name in reference_fields:
        setattr(base, name, [name])
    value = isolate_mission_scope(base, bound())
    cloned = clone_mission(value)
    assert set(vars(cloned)) == {item.name for item in fields(Mission)}
    assert vars(cloned) == vars(value)
    assert cloned._scope_state is value._scope_state
    assert deepcopy(value)._scope_state.binding_bytes == value._scope_state.binding_bytes
    for name in reference_fields:
        getattr(cloned, name).append('detached')
        assert getattr(value, name) == [name]
        assert getattr(value, name) is not getattr(base, name)


def test_clone_rejects_missing_declared_value():
    value = mission()
    del value.created_at
    with pytest.raises(ValueError, match=HOLD):
        clone_mission(value)


@pytest.mark.parametrize('structural_bound', [False, True])
def test_phase_one_rejects_instance_dictionary_subclass_before_hooks(tmp_path, structural_bound):
    truth = TruthRuntime(tmp_path / 'r1')
    controller = ClosedLoopControlPlane.bootstrap(truth, mission())
    value = isolate_mission_scope(mission(), bound()) if structural_bound else mission()
    original_scope = vars(value).get('_scope_state')
    calls = []

    class DictionaryHooks(dict):
        def copy(self):
            calls.append('copy')
            return {k: v for k, v in dict.items(self) if k != '_scope_state'}

        def get(self, key, default=None):
            calls.append('get')
            if key == '_scope_state':
                return default
            return dict.get(self, key, default)

        __iter__ = tripwire
        __contains__ = tripwire
        __getitem__ = tripwire
        keys = tripwire
        items = tripwire

    raw = DictionaryHooks(vars(value))
    value.__dict__ = raw
    before = snapshot(truth)
    actions = (
        lambda: clone_mission(value),
        lambda: isolate_mission_scope(value, bound()),
        lambda: serialize_mission_scope(value),
        lambda: to_payload(value),
        lambda: reject_reserved(value),
        lambda: truth_overlay.append_entity(truth, value, release_id='RT1', artifact_version=2),
        lambda: controller._persist_mission(value),
        lambda: controller._sync_mission(value),
    )
    for action in actions:
        with pytest.raises((ValueError, RuntimeError), match=HOLD):
            action()
    assert calls == []
    assert dict.get(raw, '_scope_state') is original_scope
    assert dict.get(raw, 'mission_id') == 'M1' and dict.get(raw, 'release_id') == 'RT1'
    assert snapshot(truth) == before


@pytest.mark.parametrize('structural_bound,collision', [(False, '_scope_state'), (True, 'scope_binding')])
def test_phase_one_rejects_non_string_instance_key_before_comparison(tmp_path, structural_bound, collision):
    truth = TruthRuntime(tmp_path / 'r1')
    controller = ClosedLoopControlPlane.bootstrap(truth, mission())
    value = isolate_mission_scope(mission(), bound()) if structural_bound else mission()
    raw = vars(value)
    original_scope = raw.get('_scope_state')
    calls = []

    class CollidingKey:
        def __hash__(self):
            calls.append('hash')
            return hash(collision)

        def __eq__(self, other):
            calls.append('comparison')
            return other == collision

    key = CollidingKey()
    raw[key] = None
    calls.clear()
    before = snapshot(truth)
    actions = (
        lambda: clone_mission(value),
        lambda: isolate_mission_scope(value, bound()),
        lambda: serialize_mission_scope(value),
        lambda: to_payload(value),
        lambda: reject_reserved(value),
        lambda: truth_overlay.append_entity(truth, value, release_id='RT1', artifact_version=2),
        lambda: controller._persist_mission(value),
    )
    for action in actions:
        with pytest.raises((ValueError, RuntimeError), match=HOLD):
            action()
    assert calls == []
    safe_fields = {name: field_value for name, field_value in dict.items(raw) if type(name) is str}
    assert safe_fields.get('_scope_state') is original_scope
    assert safe_fields['mission_id'] == 'M1' and safe_fields['release_id'] == 'RT1'
    assert snapshot(truth) == before


@pytest.mark.parametrize('path,name,code', [
    ((), 'mission_id', 'MISSION_ENVELOPE_INVALID'),
    (('scope_binding',), 'snapshot_ref', 'BINDING_STRUCTURE_INVALID'),
    (('scope_binding', 'creation_key_scope'), 'actor_ref', 'BINDING_STRUCTURE_INVALID'),
    (('scope_binding', 'mapping'), 'runtime_release_id', 'BINDING_STRUCTURE_INVALID'),
])
def test_isolated_scope_dto_rejects_alias_keys_before_parsing(path, name, code):
    calls = []

    class AliasKey:
        def __hash__(self):
            calls.append('hash')
            return hash(name)

        def __eq__(self, other):
            calls.append('comparison')
            return other == name

    envelope = bound()
    target = envelope
    for item in path:
        target = target[item]
    value = target.pop(name)
    target[AliasKey()] = value
    calls.clear()
    incoming = mission()
    with pytest.raises(BindingStructureError, match=code):
        isolate_mission_scope(incoming, envelope)
    assert calls == [] and serialize_mission_scope(incoming) == {}
