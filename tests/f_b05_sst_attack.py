import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_sst_postgres import SST
from test_dsh_workbench_b_postgres import psycopg
from tools.dsh_workbench.business_relations import import_verified_sst_link,import_verified_requirement_version
class FAttack(SST):
 def test_f_batch_proof_not_reused_and_revoke_replay(self):
  self.sst_seed();import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST1','source:link1','r1')
  self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach')
  self.store.create_batch('alice','P1','B2','2026-11-13','b2')
  self.relations.attach_member('alice','P1','B2','requirement','R1',1,'r-b2');self.relations.attach_member('alice','P1','B2','version','V1',2,'v-b2')
  import_verified_requirement_version(self.owner,'P1','B2','R1','V1','source:rv-b2','r1');self.relations.attach_requirement_version('alice','P1','B2','R1','V1',3,'rv-b2')
  self.error(422,lambda:self.relations.attach_sst('alice','P1','B2','R1','V1','SST1',4,'bad'))
  self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.request_log WHERE request_id='bad'").fetchone()[0],0)
  self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
  self.error(403,lambda:self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach'))
  self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
 def test_f_verified_link_runtime_forgery_inside_valid_scope_rejected(self):
  self.sst_seed()
  with self.assertRaises(psycopg.errors.InsufficientPrivilege):
   with self.runtime.transaction():
    self.runtime.execute("SELECT set_config('wb.principal','alice',true)")
    self.runtime.execute("INSERT INTO wb.verified_sst_link VALUES('P1','B1','R1','V1','SST1','fake','1')")
  self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.verified_sst_link').fetchone()[0],0)
