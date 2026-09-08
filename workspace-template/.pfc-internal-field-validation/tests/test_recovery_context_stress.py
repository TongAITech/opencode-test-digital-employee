"""Synthetic >=10 MiB evidence; bounded reads and real R1/G2.1 rotation lifecycle.

The external Session transport is simulated. Runtime, pressure detector,
checkpoints, successors, root lineage and final Task completion are production.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ai-test/runtime'))
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.bounded_evidence import read_evidence_page, require_router_session, mission_evidence_directory, MAX_RESPONSE_BYTES
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.session_pressure import message_metrics
from test_g2_1_session_router_control_loop import request, one_task


def main():
    with tempfile.TemporaryDirectory(prefix='recovery-context-stress-') as temp:
        root = Path(temp)
        db = root / 'state/runtime-spine.db'
        provider = FakeOpenCodeSessionProvider(root)
        def restore():
            return G21AutonomousOrchestrationService(create_canonical_runtime(root, db_path=db), root, session_provider=provider)
        service = restore()
        mission = service.start_test(request('bounded-stress', 'SYNTHETIC-CONTEXT-STRESS'))['intake']['intake']['mission_id']
        planner = next(p for p in service.session_control.state(mission).provisions if p.role == 'PLANNER')
        require_router_session(service.runtime.replay_composed(mission), planner.external_session_id)
        first = service.propose_plan(mission, one_task('CODE_ANALYST'))['next']
        require_router_session(service.runtime.replay_composed(mission), first['external_session']['session_id'])
        unbound = provider.create_session(title='core-only Session must not read evidence')
        service._open_core_session(mission_id=mission, external=unbound, task_id=None,
            agent='aitest-planner', phase='PLANNING', logical_agent_id='unbound-logical')
        for sid in ('foreign-session', unbound.session_id):
            try: require_router_session(service.runtime.replay_composed(mission), sid)
            except ValueError: pass
            else: raise AssertionError('Unrouted Session read admitted')
        directory = mission_evidence_directory(root, mission)
        assert ':' not in directory.name and len(directory.name) == 64
        directory.mkdir(parents=True)
        source = directory / 'runtime-events.jsonl'
        row = json.dumps({'classification': 'SYNTHETIC_ONLY', 'observation': 'bounded context pressure regression ' * 80}) + '\n'
        with source.open('w', encoding='utf-8') as stream:
            for _ in range(4500): stream.write(row)
        assert source.stat().st_size >= 10 * 1024 * 1024
        max_page = 0
        offset = 0
        sha = None
        predecessor = first['external_session']['session_id']
        logical = service.session_control.state(mission).provisions[-1].logical_agent_id
        for iteration in range(2):
            messages = []
            for index in range(7):
                page = read_evidence_page(root, mission, 'evidence:runtime-events.jsonl', offset=offset, expected_sha256=sha)
                sha = page['source_sha256']; offset = page['next_offset']
                serialized = json.dumps(page, ensure_ascii=False)
                assert page['returned_bytes'] <= 4096 and page['source_bytes'] > page['returned_bytes']
                max_page = max(max_page, len(serialized.encode('utf-8')))
                messages.append({'info': {'id': f'page-{index}', 'sessionID': predecessor, 'role': 'assistant'},
                                 'parts': [{'type': 'tool', 'state': {'output': serialized}}]})
            pressure = message_metrics(messages, predecessor)
            provider.set_observation(predecessor, pressure=pressure, message_count=len(messages))
            # A restarted control-loop service discovers pressure and requests
            # rotation; no worker calls observe_session or rotate_session.
            service = restore()
            tick = service.supervise_once()
            state = service.session_control.state(mission)
            rotations = [r for r in state.rotations if r.task_id == first['task_id']]
            assert len(rotations) == iteration + 1, tick
            rotation = rotations[-1]
            assert rotation.status == 'COMPLETED', rotation
            assert rotation.checkpoint['mission_id'] == mission
            assert rotation.checkpoint['task_id'] == first['task_id']
            assert rotation.checkpoint['logical_agent_id'] == logical
            assert rotation.checkpoint['root_attempt_id'] == first['attempt']['root_attempt_id']
            composed = service.runtime.replay_composed(mission)
            latest = composed.extension_state('r1_3b_execution_resume').latest_attempt(first['task_id'])
            assert latest.root_attempt_id == first['attempt']['root_attempt_id']
            assert latest.runtime_session_id != predecessor
            assert composed.core_state.session(predecessor).status.value == 'CLOSED'
            try: require_router_session(composed, predecessor)
            except ValueError: pass
            else: raise AssertionError('Closed predecessor read admitted')
            require_router_session(composed, latest.runtime_session_id)
            predecessor = latest.runtime_session_id
            bootstrap = next(m['text'] for m in reversed(provider.messages) if m['session_id'] == predecessor)
            assert len(bootstrap.encode('utf-8')) <= 16384
            envelope = json.loads(bootstrap.split('\n', 1)[1])
            assert envelope['logical_agent_id'] == logical and envelope['task_id'] == first['task_id']
            assert envelope['resume_checkpoint']['mission_id'] == mission
        completed = service.report_task_outcome(mission, task_id=first['task_id'], attempt_id=latest.attempt_id,
            session_id=latest.runtime_session_id, outcome='SUCCEEDED', summary='Synthetic bounded source references verified after two automatic rotations')
        assert completed['next']['status'] == 'PLAN_COMPLETE'
        # Reader budgets, source pinning and path controls cannot be bypassed.
        for extras in ({'limit': 10 * 1024 * 1024}, {'offset': -1}, {'offset': 4096}, {'offset': 4096, 'expected_sha256': 'invalid'}, {'expected_sha256': '0' * 64}):
            try: read_evidence_page(root, mission, 'evidence:runtime-events.jsonl', **extras)
            except ValueError: pass
            else: raise AssertionError('reader accepted unbounded/unpinned input')
        for ref in ('evidence:../runtime-events.jsonl', 'evidence:/etc/passwd', 'evidence:C:/host.json', 'file:/etc/passwd'):
            try: read_evidence_page(root, mission, ref)
            except ValueError: pass
            else: raise AssertionError('reader accepted arbitrary host path')
        sibling = mission_evidence_directory(root, 'other-mission')
        sibling.mkdir()
        (sibling / 'private.jsonl').write_text('other Mission evidence', encoding='utf-8')
        alias = mission_evidence_directory(root, 'aliased-mission')
        try:
            alias.symlink_to(sibling, target_is_directory=True)
        except OSError:
            if sys.platform != 'win32': raise
            import subprocess
            made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(sibling)], capture_output=True)
            if made.returncode: raise AssertionError('Cannot verify Windows Mission junction guard')
        try: read_evidence_page(root, 'aliased-mission', 'evidence:private.jsonl')
        except ValueError as exc: assert 'PATH_FORBIDDEN' in str(exc)
        else: raise AssertionError('Cross-Mission directory redirect exposed evidence')
        secret = directory / 'sensitive.json'
        secret.write_text('{"apiKey":"synthetic-secret"}', encoding='utf-8')
        try: read_evidence_page(root, mission, 'evidence:sensitive.json')
        except ValueError as exc: assert 'SECRET_MATERIAL_FORBIDDEN' in str(exc)
        else: raise AssertionError('secret material exposed')
        assert max_page <= MAX_RESPONSE_BYTES
        assert not (root / 'ai-test/state/aitest.db').exists()
        print(json.dumps({'status': 'PASS', 'classification': 'SYNTHETIC_CONTEXT_STRESS_SIMULATED_TRANSPORT',
            'gates': {'AUTO_ROTATION': 'PASS', 'SUCCESSOR_RESUME': 'PASS', 'CONTEXT_STRESS': 'PASS'},
            'source_bytes': source.stat().st_size, 'max_response_bytes': max_page, 'rotation_count': 2,
            'same_mission_task_logical_agent_root_attempt': True, 'task_completed': True,
            'RAW_LARGE_RUNTIME_FILE_DIRECT_CONTEXT_INJECTION': 'FORBIDDEN',
            'overflow_count': 0, 'CONTEXT_TOO_LARGE_ERROR': 0, 'AI_APICallError_CONTEXT_OVERFLOW': 0,
            'model_context_overflow_measurement': 'NOT_APPLICABLE_NO_REAL_MODEL',
            'BANK_FIELD_VALIDATION_REQUIRED': True}, indent=2))
    return 0

if __name__ == '__main__': raise SystemExit(main())
