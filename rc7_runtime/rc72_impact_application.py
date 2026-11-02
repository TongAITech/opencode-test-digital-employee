"""Durable, scoped application of a frozen stale-propagation decision.

An impact is decided once before any asset mutation. Partial application resumes
against the original versions. Completed replay is historical and never stales
assets rebuilt after that decision. This is not a cross-process lock.
"""
from dataclasses import asdict
import hashlib
import json

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState, ObligationStatus, ETUState
from .rc72_impact import ImpactSet, ImpactStrategy
from .rc72_impact_truth import append_impact_set, install_rc72_impact_truth_overlay

_KIND = 'rc72_impact_application'
_EVENT = 'RC72_IMPACT_APPLICATION_UPSERTED'


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _validate(payload):
    out = dict(payload)
    for key in ('application_id', 'release_id', 'mission_id', 'source_sha256'):
        contracts._require_str(out, key)
    if out.get('state') not in {'PLANNED', 'APPLIED'} or not isinstance(out.get('impact'), dict):
        raise contracts.DomainValidationError('IMPACT_APPLICATION_STATE_INVALID')
    if not isinstance(out.get('targets'), list):
        raise contracts.DomainValidationError('IMPACT_APPLICATION_TARGETS_REQUIRED')
    for target in out['targets']:
        if set(target) != {'kind', 'identity_key', 'original'} or not isinstance(target['original'], dict):
            raise contracts.DomainValidationError('IMPACT_APPLICATION_TARGET_INVALID')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_impact_application_overlay():
    install_rc72_impact_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'application_id')
    registry.BUCKETS[_KIND] = 'rc72_impact_applications'
    registry.IDENTITY_FIELDS[_KIND] = 'application_id'


def _one(truth, kind, **filters):
    rows = truth.query(kind, **filters)
    if len(rows) != 1:
        raise ContractError('IMPACT_APPLICATION_PARENT_NOT_UNIQUE:' + kind)
    return rows[0]


def _decide(runtime, source, changed_refs, reason, application_id):
    truth, mission = runtime.truth, source['mission_id']
    changed = set(changed_refs)
    nodes, obligations, etus, affected = {}, {}, {}, []
    for delivery in truth.query('rc72_node_delivery', mission_id=mission):
        if delivery['delivery_id'] != source['delivery_id'] and set(delivery.get('input_refs') or []) & changed:
            node = runtime.node(delivery['mission_node_id'])
            nodes[node['mission_node_id']] = node
            affected.append(delivery['delivery_id'])
    for obligation in truth.query('rc72_test_obligation', mission_id=mission):
        refs = set(obligation.get('code_slice_refs') or []) | set(obligation.get('change_refs') or [])
        if refs & changed:
            obligations[obligation['obligation_id']] = obligation
            affected.append(obligation['obligation_id'])
    for etu in truth.query('rc72_etu', mission_id=mission):
        if etu['obligation_id'] in obligations or etu['primary_code_slice'] in changed:
            etus[etu['etu_id']] = etu
            affected.append(etu['etu_id'])
    strategy = ImpactStrategy.EXPLICIT_DEPENDENCY
    if not (nodes or obligations or etus):
        strategy = ImpactStrategy.SAFE_FALLBACK
        ordered = list(AutonomousMissionNode.ordered())
        for kind in ordered[ordered.index(AutonomousMissionNode(source['node_type'])) + 1:]:
            if kind in {AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY, AutonomousMissionNode.N9_DEFECT,
                        AutonomousMissionNode.N10_RELEASE_CONVERGENCE}:
                continue
            node = runtime.node_by_type(mission, kind)
            if node['state'] != 'NOT_STARTED':
                nodes[node['mission_node_id']] = node
                affected.append(node['mission_node_id'])
        for obligation in truth.query('rc72_test_obligation', mission_id=mission):
            obligations[obligation['obligation_id']] = obligation
            affected.append(obligation['obligation_id'])
        for etu in truth.query('rc72_etu', mission_id=mission):
            etus[etu['etu_id']] = etu
            affected.append(etu['etu_id'])
    impact = ImpactSet(impact_set_id='IMPACT-' + application_id.split('-', 1)[1], mission_id=mission,
        source_mission_node_id=source['mission_node_id'], source_node_type=source['node_type'],
        source_delivery_id=source['delivery_id'], changed_refs=list(changed_refs),
        affected_refs=list(dict.fromkeys(affected)), stale_mission_node_ids=list(nodes),
        stale_obligation_ids=list(obligations), stale_etu_ids=list(etus), strategy=strategy, reason=reason)
    targets = [dict(kind=kind, identity_key=key, original=row) for kind, key, rows in (
        ('rc72_mission_node', 'mission_node_id', nodes),
        ('rc72_test_obligation', 'obligation_id', obligations), ('rc72_etu', 'etu_id', etus))
        for row in rows.values()]
    return impact, targets


def _pending_target(truth, target, reason):
    original, kind, key = target['original'], target['kind'], target['identity_key']
    if (kind, key) not in {('rc72_mission_node', 'mission_node_id'),
                          ('rc72_test_obligation', 'obligation_id'), ('rc72_etu', 'etu_id')}:
        raise ContractError('IMPACT_APPLICATION_TARGET_INVALID')
    current = _one(truth, kind, **{key: original[key]})
    state_key = 'status' if kind == 'rc72_test_obligation' else 'state'
    if current == original:
        return None if current[state_key] == 'STALE' else current
    if kind == 'rc72_mission_node' and (
            current.get('blocked_reason') != reason
            or current.get('revision') != int(original.get('revision') or 1) + 1):
        raise ContractError('IMPACT_APPLICATION_TARGET_CHANGED:' + original[key])
    ignored = {'artifact_version', 'updated_at', state_key}
    if kind == 'rc72_mission_node':
        ignored.update({'revision', 'blocked_reason'})
    # Only the single expected invalidation write may have happened. A newer
    # version means another actor changed/rebuilt the target and requires audit.
    if (current.get(state_key) != 'STALE'
            or current['artifact_version'] != original['artifact_version'] + 1
            or {k: v for k, v in current.items() if k not in ignored}
                != {k: v for k, v in original.items() if k not in ignored}):
        raise ContractError('IMPACT_APPLICATION_TARGET_CHANGED:' + original[key])
    return None


def apply_stale_impact(runtime, *, source_delivery_id, changed_refs, reason):
    install_rc72_impact_application_overlay()
    if (not isinstance(changed_refs, (list, tuple)) or not changed_refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in changed_refs)):
        raise ContractError('STALE_PROPAGATION_REQUIRES_CHANGED_REFS')
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError('IMPACT_REASON_REQUIRED')
    source = _one(runtime.truth, 'rc72_node_delivery', delivery_id=source_delivery_id)
    if source.get('release_id') != runtime.release_id:
        raise ContractError('IMPACT_SOURCE_RELEASE_MISMATCH')
    application_id = 'IMPACTAPP-' + _hash([runtime.release_id, source['mission_id'],
                                          source_delivery_id, list(changed_refs), reason])[:24]
    prior = runtime.truth.query(_KIND, application_id=application_id)
    if prior:
        row = _one(runtime.truth, _KIND, application_id=application_id)
        if row['source_sha256'] != _hash(source) or row['release_id'] != runtime.release_id:
            raise ContractError('IMPACT_APPLICATION_SOURCE_CHANGED')
        impact = ImpactSet(**row['impact'])
        if (impact.mission_id != source['mission_id'] or impact.source_delivery_id != source_delivery_id
                or impact.changed_refs != list(changed_refs) or impact.reason != reason):
            raise ContractError('IMPACT_APPLICATION_REPLAY_CONFLICT')
    else:
        impact, targets = _decide(runtime, source, changed_refs, reason, application_id)
        row = dict(application_id=application_id, release_id=runtime.release_id,
            mission_id=source['mission_id'], source_sha256=_hash(source), impact=asdict(impact),
            targets=targets, state='PLANNED', artifact_version=1)
        runtime.truth.append_atomic(_EVENT, row)
    expected_targets = [
        ('rc72_mission_node', 'mission_node_id', key) for key in impact.stale_mission_node_ids
    ] + [('rc72_test_obligation', 'obligation_id', key) for key in impact.stale_obligation_ids
    ] + [('rc72_etu', 'etu_id', key) for key in impact.stale_etu_ids]
    actual_targets = [(target['kind'], target['identity_key'],
                       target['original'].get(target['identity_key'])) for target in row['targets']]
    if (impact.impact_set_id != 'IMPACT-' + application_id.split('-', 1)[1]
            or row['mission_id'] != source['mission_id'] or actual_targets != expected_targets
            or len(actual_targets) != len(set(actual_targets))
            or any(target['original'].get('mission_id') != source['mission_id']
                   or target['original'].get('release_id') != runtime.release_id for target in row['targets'])):
        raise ContractError('IMPACT_APPLICATION_TARGET_SCOPE_CHANGED')
    existing = runtime.truth.query('rc72_impact_set', impact_set_id=impact.impact_set_id)
    if existing:
        expected = dict(asdict(impact), artifact_type='rc72_impact_set',
                        artifact_version=1, release_id=runtime.release_id)
        if len(existing) != 1 or existing[0] != expected:
            raise ContractError('IMPACT_APPLICATION_RECORD_CHANGED')
    elif row['state'] == 'APPLIED':
        raise ContractError('IMPACT_APPLICATION_RECORD_MISSING')
    else:
        append_impact_set(runtime.truth, impact, release_id=runtime.release_id)
    if row['state'] == 'APPLIED':
        return impact
    # Preflight the entire frozen denominator before any resumed mutation.
    stale_reason = 'SAFE_FALLBACK: ' + reason if impact.strategy == ImpactStrategy.SAFE_FALLBACK else reason
    pending = [(target['kind'], _pending_target(runtime.truth, target, stale_reason)) for target in row['targets']]
    for kind, target in pending:
        if target is None:
            continue
        if kind == 'rc72_mission_node':
            runtime.mark_stale(target['mission_node_id'], reason=stale_reason)
        elif kind == 'rc72_test_obligation':
            runtime._persist_obligation_status(target, ObligationStatus.STALE)
        else:
            runtime._persist_etu_state(target, ETUState.STALE)
    runtime.truth.append_atomic(_EVENT, dict(row, state='APPLIED', artifact_version=2))
    return impact


install_rc72_impact_application_overlay()
