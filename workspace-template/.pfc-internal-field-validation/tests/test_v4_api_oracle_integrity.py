"""Independent F08/F29 Oracle controls; real loopback HTTP, synthetic DB/CAT.

No model, bank target, real database or UNKNOWN_SIDE_EFFECT qualification.
"""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_rec3_business_contracts import standard_case
from aitest_runtime.recovery_api import run_journey, MAX_DIAGNOSTIC_BYTES
from aitest_runtime.recovery_executors import OfflineExecutor


class SyntheticService(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        self.server.calls += 1
        raw = self.server.body
        self.send_response(200); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


class ObservationProvider:
    def __init__(self, values): self.values = list(values); self.calls = []
    def read(self, query, parameters):
        self.calls.append((query, copy.deepcopy(parameters)))
        value = self.values[len(self.calls)-1]
        if isinstance(value, Exception): raise value
        return copy.deepcopy(value)


def journey(origin, channels=('DB',), *, extra_assertions=()):
    return {'steps': [{'step_id': 'inspect-business', 'url': origin + '/state', 'method': 'GET',
        'status_code': 200, 'assertions': [{'op': 'eq', 'path': '$.code', 'value': 'OK'}, *extra_assertions],
        'cross_channel': [{'channel': channel, 'binding_query_id': f'{channel.lower()}-{index}',
                           'parameters': {'scope': 'synthetic-only'},
                           'assertion': {'op': 'eq', 'path': '$.ok', 'value': True}}
                          for channel in channels for index in range(3)]}]}


class OracleIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticService)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def setUp(self):
        self.server.body = b'{"code":"OK","amount":7}'
        self.server.calls = 0
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config = {'approved': True, 'approval_ref': 'SYNTHETIC-ONLY',
                       'allowed_origins': [self.origin], 'allowed_methods': ['GET']}

    def execute(self, profile, providers=None, case=None):
        executor = OfflineExecutor(self.temp.name, 'API', self.config, oracle_providers=providers)
        return run_journey(executor, case or standard_case({'api_journey': profile}),
                           {'authorized_scope': {'origins': [self.origin]}})

    def test_each_channel_first_middle_last_failure_and_positive_controls(self):
        for channel in ('DB', 'CAT'):
            for failing in (0, 1, 2, None):
                with self.subTest(channel=channel, failing=failing):
                    provider = ObservationProvider([{'ok': i != failing} for i in range(3)])
                    before = self.server.calls
                    actual, passed = self.execute(journey(self.origin, (channel,)), {channel: provider})
                    self.assertEqual(passed, failing is None)
                    self.assertEqual(self.server.calls-before, 1)
                    self.assertEqual(len(provider.calls), 3)
                    records = actual['steps'][0]['oracles']
                    self.assertEqual(len(records), 5); self.assertEqual(len({r['oracle_id'] for r in records}), 5)
                    channel_records = [r for r in records if r['channel'] == channel]
                    self.assertEqual([r['status'] for r in channel_records], ['FAIL' if i == failing else 'PASS' for i in range(3)])
                    self.assertTrue(all(r['mandatory'] for r in channel_records))
                    if failing is not None:
                        diagnosis = channel_records[failing]['diagnostic']
                        self.assertEqual(diagnosis['expected']['value'], True)
                        self.assertEqual(diagnosis['actual'], False)
                        self.assertEqual(diagnosis['diff'], 'VALUE_MISMATCH')

    def test_missing_exception_and_invalid_assertion_are_individual_errors(self):
        for channel in ('DB', 'CAT'):
            for bad in (None, {}, ValueError('DO_NOT_PERSIST_PROVIDER_MESSAGE')):
                with self.subTest(channel=channel, bad=type(bad).__name__):
                    provider = ObservationProvider([{'ok': True}, bad, {'ok': True}])
                    actual, passed = self.execute(journey(self.origin, (channel,)), {channel: provider})
                    records = [r for r in actual['steps'][0]['oracles'] if r['channel'] == channel]
                    self.assertFalse(passed); self.assertEqual(records[1]['status'], 'ERROR')
                    self.assertEqual(records[2]['status'], 'PASS'); self.assertEqual(len(provider.calls), 3)
                    self.assertNotIn('DO_NOT_PERSIST_PROVIDER_MESSAGE', json.dumps(actual))
        profile = journey(self.origin, (), extra_assertions=[{'op': 'expression', 'expression': '1 / 0 > 1'}])
        actual, passed = self.execute(profile)
        self.assertFalse(passed); self.assertEqual(actual['steps'][0]['oracles'][-1]['status'], 'ERROR')

    def test_absent_provider_and_bad_response_never_pass(self):
        actual, passed = self.execute(journey(self.origin))
        self.assertFalse(passed)
        self.assertEqual([r['status'] for r in actual['steps'][0]['oracles']][-3:], ['ERROR']*3)
        self.server.body = b'not-json'
        actual, passed = self.execute(journey(self.origin, ()))
        self.assertFalse(passed); self.assertEqual(actual['steps'][0]['oracles'][1]['status'], 'ERROR')

    def test_optional_failure_does_not_erase_or_downgrade_mandatory_failure(self):
        profile = journey(self.origin)
        profile['steps'][0]['cross_channel'][0]['mandatory'] = False
        actual, passed = self.execute(profile, {'DB': ObservationProvider([{'ok': False}, {'ok': True}, {'ok': True}])})
        self.assertTrue(passed); self.assertEqual(actual['steps'][0]['oracles'][2]['status'], 'FAIL')
        actual, passed = self.execute(profile, {'DB': ObservationProvider([{'ok': False}, {'ok': False}, {'ok': True}])})
        self.assertFalse(passed)

    def test_frozen_expectation_mismatch_and_missing_binding_rejected_before_send(self):
        mutations = [
            lambda c: c['expected_results'][0]['api']['assertions'][0].update(value='REJECTED'),
            lambda c: c['execution_profile']['api_journey']['steps'][0]['assertions'].clear(),
            lambda c: c['execution_profile']['api_journey']['steps'][0]['cross_channel'][0].update(mandatory=False),
            lambda c: c['execution_profile']['api_journey']['steps'][0]['cross_channel'][0].update(binding_query_id='different-query'),
            lambda c: c['execution_profile']['api_journey'].update(variables={'minimum': 0}),
            lambda c: c['oracle_contract'].pop('api_oracle_version'),
            lambda c: c['expected_results'][0].pop('api'),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                profile = journey(self.origin); case = standard_case({'api_journey': copy.deepcopy(profile)})
                mutation(case); before = self.server.calls
                with self.assertRaises(Exception): self.execute(profile, case=case)
                self.assertEqual(self.server.calls, before)

    def test_duplicate_step_ids_and_nonboolean_mandatory_rejected_before_send(self):
        profile = journey(self.origin)
        profile['steps'].append(copy.deepcopy(profile['steps'][0]))
        with self.assertRaises(Exception): self.execute(profile)
        profile = journey(self.origin); profile['steps'][0]['cross_channel'][0]['mandatory'] = 'false'
        with self.assertRaises(Exception): self.execute(profile)
        self.assertEqual(self.server.calls, 0)

    def test_failed_prerequisite_never_sends_later_step_and_missing_ids_remain_open(self):
        profile = journey(self.origin)
        later = copy.deepcopy(profile['steps'][0]); later['step_id'] = 'must-not-send'; profile['steps'].append(later)
        provider = ObservationProvider([{'ok': False}, {'ok': True}, {'ok': True}])
        actual, passed = self.execute(profile, {'DB': provider})
        self.assertFalse(passed); self.assertFalse(actual['complete']); self.assertEqual(self.server.calls, 1)
        self.assertEqual(actual['oracle_summary']['declared'], 10)
        self.assertEqual(len(actual['oracle_summary']['missing_mandatory_ids']), 5)

    def test_oracle_ids_stable_across_execution_but_unique_across_channels(self):
        ids = []
        for _ in range(2):
            actual, passed = self.execute(journey(self.origin, ('DB','CAT')),
                {ch: ObservationProvider([{'ok': True}]*3) for ch in ('DB','CAT')})
            self.assertTrue(passed); ids.append([r['oracle_id'] for r in actual['steps'][0]['oracles']])
        self.assertEqual(ids[0], ids[1]); self.assertEqual(len(set(ids[0])), 8)

    def test_frozen_array_assertion_resolves_the_same_bound_variables(self):
        self.server.body = b'{"code":"OK","values":[7]}'
        profile = journey(self.origin, (), extra_assertions=[{'op':'eq','path':'$.values','value':['${limit}']}])
        profile['variables'] = {'limit':7}
        actual, passed = self.execute(profile)
        self.assertTrue(passed)
        self.assertEqual(actual['steps'][0]['oracles'][-1]['diagnostic']['expected']['value'],[7])

    def test_diagnostic_values_bounded_and_sensitive_fields_redacted(self):
        body = {'code': 'OK', 'amount': 7, 'access_token': 'NEVER_COPY_THIS_SECRET', 'huge': '数'*10000}
        self.server.body = json.dumps(body, ensure_ascii=False).encode()
        profile = journey(self.origin, (), extra_assertions=[
            {'op':'eq','path':'$.amount','value':9},
            {'op':'eq','path':'$.access_token','value':'different'},
            {'op':'eq','path':'$.huge','value':'wrong'}])
        actual, passed = self.execute(profile); self.assertFalse(passed)
        rows = actual['steps'][0]['oracles']; numeric = rows[2]['diagnostic']
        self.assertEqual(numeric['expected']['value'],9); self.assertEqual(numeric['actual'],7)
        self.assertNotIn('NEVER_COPY_THIS_SECRET',json.dumps(actual)); self.assertNotIn('access_token',json.dumps(actual))
        self.assertTrue(all(len(json.dumps(r['diagnostic'],ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES for r in rows))
        self.assertLess(len(json.dumps(actual,ensure_ascii=False).encode()),256*1024)

    def test_canonical_failure_and_frozen_expected_survive_reconstruction(self):
        from test_recovery_browser import governed_case, exec_task
        from test_g2_1_session_router_control_loop import request
        from aitest_runtime.canonical_runtime import create_canonical_runtime
        from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
        from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
        from aitest_runtime.g4.service import G4RealExecutionService
        root = Path(self.temp.name)
        env = {'AITEST_WORKSPACE_ROOT': str(root), 'AITEST_RUNTIME_SPINE_DB': str(root/'runtime.db'), 'PFC_LOCAL_STATE_ROOT': str(root)}
        with patch.dict(os.environ, env):
            runtime = create_canonical_runtime(root, db_path=root/'runtime.db')
            orch = G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
            mission = orch.start_test(request('oracle-canonical','V4'))['intake']['intake']['mission_id']
            fact, strategy = governed_case(root,runtime,mission,{'api_journey':journey(self.origin,('DB','CAT'))})
            case = fact['payload']['r3_3_case']
            first = orch.propose_plan(mission,{'objective':'Verify all frozen mandatory Oracle observations',
                'tasks':[exec_task('oracle-check',fact['fact_id'])], 'dependencies':[]})['next']
            providers = {'DB':ObservationProvider([{'ok':False},{'ok':True},{'ok':True}]),
                         'CAT':ObservationProvider([{'ok':True},{'ok':False},{'ok':True}])}
            g4 = G4RealExecutionService(runtime,orchestration=orch,capability_executors={'API':OfflineExecutor(root,'API',self.config,oracle_providers=providers)})
            g4.create_goal(mission,{'goal_id':'goal-oracle','project_id':'LOCAL','release_id':'1.13.0',
                'requirement_scope':['LOCAL-REQUIREMENT'],'affected_applications':['local-target'],
                'affected_application_target_versions':{'local-target':'1.13.0'},'coverage_policy':{'target_pct':95}})
            g4.create_batch(mission,{'batch_id':'batch-oracle','goal_id':'goal-oracle','case_refs':[fact['fact_id']],
                'strategy_version_id':strategy,'target_application':'local-target','status':'RUNNING'})
            g4.execute_capability(mission,{'task_id':first['task_id'],'attempt_id':first['attempt']['attempt_id'],
                'session_id':first['external_session']['session_id'],'case_id':case['tc_id'],'case_version':case['case_version_id'],
                'execution_batch_id':'batch-oracle','goal_id':'goal-oracle','capability_id':'API',
                'step':{'step_id':'oracle-observe','expected':{'fake':'Caller says only HTTP 200 matters'}},
                'executor_request':{'url':self.origin+'/state','method':'GET','authorized_scope':{'origins':[self.origin]}}})
            restored = create_canonical_runtime(root,db_path=root/'runtime.db')
            result = G4RealExecutionService(restored).state(mission).latest('EXECUTION_STEP_RESULT').payload
            self.assertEqual(result['oracle_result'],'FAIL')
            self.assertEqual(result['expected']['expected_results'],case['expected_results'])
            self.assertNotIn('fake',result['expected'])
            rows = result['actual']['steps'][0]['oracles']
            self.assertEqual(len(rows),8); self.assertEqual(sum(r['status']=='FAIL' for r in rows),2)
            self.assertTrue(restored.verify_projection(mission)['ok'])
            self.assertEqual(self.server.calls,1)


if __name__ == '__main__': unittest.main(verbosity=2)
