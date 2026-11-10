import copy
import unittest
from tools.dsh_workbench.e02_lineage import validate_lineage
from tools.dsh_workbench.business_store import BusinessError

class Lineage(unittest.TestCase):
    def seed(self):
        kinds=('rc72_mission_node','rc72_node_delivery','rc72_node_gate','rc72_node_transition','rc72_back_edge','rc7_task','rc72_etu','rc72_workitem_attempt_binding','execution_attempt','rc72_test_obligation')
        data={k:[] for k in kinds}
        def add(kind,**row):data[kind].append(dict(mission_id='M1',release_id='B1',**row))
        add('rc72_mission_node',mission_node_id='N',node_type='N1_REALITY',delivery_refs=['D'],gate_refs=['G'],active_delivery_version=1)
        add('rc72_node_delivery',delivery_id='D',mission_node_id='N',node_type='N1_REALITY',version=1)
        add('rc72_node_gate',gate_id='G',delivery_id='D',mission_node_id='N',node_type='N1_REALITY')
        add('rc7_task',task_id='W')
        add('rc72_test_obligation',obligation_id='O',release_batch_id='B1')
        add('rc72_etu',etu_id='E',obligation_id='O',release_batch_id='B1',case_ids=['C'])
        add('execution_attempt',attempt_id='A',tc_id='C')
        add('rc72_workitem_attempt_binding',binding_id='B',etu_id='E',workitem_id='W',case_id='C',attempt_id='A',state='COMPLETED',mission_node_id='N',mission_node_type='N1_REALITY')
        return data
    def test_positive_and_each_reference_mismatch_rejects(self):
        mission={'mission_id':'M1','release_id':'B1'};data=self.seed();validate_lineage(data,mission,'B1')
        for kind,key in [('rc72_node_gate','delivery_id'),('rc72_node_delivery','mission_node_id'),('rc72_workitem_attempt_binding','etu_id'),('rc72_workitem_attempt_binding','workitem_id'),('rc72_workitem_attempt_binding','attempt_id'),('rc72_workitem_attempt_binding','case_id'),('rc72_workitem_attempt_binding','mission_node_id'),('rc72_etu','obligation_id'),('rc72_etu','release_batch_id')]:
            changed=copy.deepcopy(data);changed[kind][0][key]='FOREIGN'
            with self.subTest(kind=kind,key=key),self.assertRaises(BusinessError):validate_lineage(changed,mission,'B1')
        changed=copy.deepcopy(data);changed['rc72_node_delivery'][0]['mission_id']='M2'
        with self.assertRaises(BusinessError):validate_lineage(changed,mission,'B1')
        changed=copy.deepcopy(data);changed['execution_attempt'][0]['tc_id']='other'
        with self.assertRaises(BusinessError):validate_lineage(changed,mission,'B1')
