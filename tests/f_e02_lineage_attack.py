import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_e02_postgres import E02
from tools.dsh_workbench.e02_service import E02Service
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_runtime.rc72_domain import MissionNodeRecord,NodeDelivery,NodeGate
class FAttack(E02):
 def test_f_gate_foreign_node_same_release_rejected(self):
  self.scope_seed();self.setup_r1();truth=TruthRuntime(self.r1)
  append_rc72_entity(truth,MissionNodeRecord(mission_node_id='FOREIGN_NODE',mission_id='M2',node_type='N1_REALITY',scope_ref='OTHER_SCOPE'),release_id='B1')
  append_rc72_entity(truth,NodeDelivery(delivery_id='FOREIGN_DELIVERY',mission_id='M2',mission_node_id='FOREIGN_NODE',node_type='N1_REALITY',version=1,producer_ref='worker'),release_id='B1')
  append_rc72_entity(truth,NodeGate(gate_id='GATE1',mission_id='M1',mission_node_id='FOREIGN_NODE',node_type='N1_REALITY',delivery_id='FOREIGN_DELIVERY',decision='PASS',reviewer_worker_id='reviewer',reviewer_session_id='session',criteria=['criterion']),release_id='B1')
  before=self.r1.read_bytes()
  self.error(503,lambda:E02Service(self.scope,self.r1,self.root).graph('alice','P1','B1','2026-11-12','M1'))
  self.assertEqual(before,self.r1.read_bytes())
