import unittest
from tools.dsh_workbench.e02_service import E02Service
from tools.dsh_workbench.e01_service import E01Service
from unittest.mock import patch
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_runtime.rc72_domain import MissionNodeRecord,NodeDelivery,NodeGate
from rc7_runtime.rc72_domain import TestObligation as RuntimeObligation
from rc6_runtime.truth import TruthRuntime
import test_dsh_workbench_e01_postgres as prior

@unittest.skipUnless(prior.prior.prior.prior.DSN and prior.prior.prior.prior.psycopg,'real PG required')
class E02(prior.E01):
    def test_unreferenced_obligation_requires_the_authorized_batch(self):
        self.scope_seed()
        self.setup_r1()
        runtime = TruthRuntime(self.r1)

        def obligation(identity, batch):
            return RuntimeObligation(
                obligation_id=identity, mission_id='M1', release_batch_id=batch,
                requirement_id='R1', sst_id='SST1', application_id='APP',
                business_scenario='fixture', business_rule='fixture rule',
                risk_level='HIGH', test_level='SST', oracle_refs=['fixture://rule'],
            )

        append_rc72_entity(runtime, obligation('OBL-LOCAL', 'B1'), release_id='B1')
        with patch('test_dsh_workbench_e01_postgres.E01Service', E02Service):
            origin = self.quality_server()
            paths = [
                '/api/workbench/v1/missions/M1/%s?project_id=P1&batch_id=B1&release_date=2026-11-12'
                % view for view in ('graph', 'workitems')
            ]
            for path in paths:
                self.assertEqual(self.http(origin, path)[0], 200)
            append_rc72_entity(runtime, obligation('OBL-FOREIGN', 'B2'), release_id='B1')
            before = self.r1.read_bytes()
            for path in paths:
                self.assertEqual(self.http(origin, path),
                                 (503, {'error': {'code': 'R1_LINEAGE_UNRESOLVED'}}))
            self.assertEqual(self.r1.read_bytes(), before)

    def test_graph_canonical_missing_cold_recovery_scope_and_unknown_reject(self):
        self.scope_seed();self.setup_r1()
        runtime=TruthRuntime(self.r1)
        append_rc72_entity(runtime,MissionNodeRecord(mission_node_id='NODE1',mission_id='M1',node_type='N1_REALITY',scope_ref='B1'),release_id='B1')
        before=self.r1.read_bytes()
        provider_patch=patch('test_dsh_workbench_e01_postgres.E01Service',E02Service)
        provider_patch.start();self.addCleanup(provider_patch.stop)
        origin=self.quality_server()
        path='/api/workbench/v1/missions/M1/graph?project_id=P1&batch_id=B1&release_date=2026-11-12'
        status,value=self.http(origin,path);self.assertEqual(status,200,value)
        self.assertEqual(value['records']['rc72_mission_node'][0]['state'],'NOT_STARTED')
        self.assertEqual(len(value['missing_nodes']),9);self.assertEqual(value['release_decision'],'HOLD')
        self.assertEqual(value['human_approval'],'UNKNOWN_NOT_QUERIED')
        self.assertEqual(self.http(origin,path.replace('/graph?','/workitems?'))[0],200)
        self.assertEqual(self.http(origin,path.replace('batch_id=B1','batch_id=wrong'))[0],404)
        self.assertEqual(self.http(origin,path,False)[0],403)
        self.assertEqual(self.http(origin,path+'&principal=alice')[0],400)
        self.assertEqual(before,self.r1.read_bytes())
        append_rc72_entity(runtime,MissionNodeRecord(mission_node_id='FOREIGN_NODE',mission_id='M2',node_type='N1_REALITY',scope_ref='B1'),release_id='B1')
        append_rc72_entity(runtime,NodeDelivery(delivery_id='FOREIGN_DELIVERY',mission_id='M2',mission_node_id='FOREIGN_NODE',node_type='N1_REALITY',version=1,producer_ref='fixture'),release_id='B1')
        append_rc72_entity(runtime,NodeGate(gate_id='BAD_GATE',mission_id='M1',mission_node_id='FOREIGN_NODE',node_type='N1_REALITY',delivery_id='FOREIGN_DELIVERY',decision='PASS',reviewer_worker_id='reviewer',reviewer_session_id='fresh',criteria=['fixture']),release_id='B1')
        attack=self.r1.read_bytes()
        self.assertEqual(self.http(origin,path)[0],503)
        self.assertEqual(self.http(origin,path.replace('/graph?','/workitems?'))[0],503)
        self.assertEqual(attack,self.r1.read_bytes())
        self.r1.write_bytes(before)
        self.assertEqual(self.http(origin,path)[0],200)
        self.r1.write_bytes(before.replace(b'NOT_STARTED',b'INVENTED_PASS'))
        self.assertEqual(self.http(origin,path)[0],503)
        self.r1.write_bytes(before)
        self.assertEqual(self.http(origin,path)[0],200)
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.assertEqual(self.http(origin,path)[0],403)
