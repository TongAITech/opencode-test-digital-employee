import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_relations_postgres import RequirementVersion
from tools.dsh_workbench.business_relations import import_verified_requirement_version
from tools.dsh_workbench.business_migrations import downgrade
class FAttack(RequirementVersion):
 def ready(self):
  self.seed();self.relations.attach_member('alice','P1','B1','requirement','R1',1,'ar');self.relations.attach_member('alice','P1','B1','version','V1',2,'av')
 def test_f_cross_batch_source_not_inherited_and_reject_atomic(self):
  self.ready();import_verified_requirement_version(self.owner,'P1','B1','R1','V1','source:rv','r1')
  self.store.create_batch('alice','P1','B2','2026-11-13','b2')
  self.relations.attach_member('alice','P1','B2','requirement','R1',1,'ar2');self.relations.attach_member('alice','P1','B2','version','V1',2,'av2')
  self.error(422,lambda:self.relations.attach_requirement_version('alice','P1','B2','R1','V1',3,'bad'))
  self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.request_log WHERE request_id='bad'").fetchone()[0],0)
  self.assertEqual(self.owner.execute("SELECT relation_revision FROM wb.release_batch WHERE batch_id='B2'").fetchone()[0],3)
 def test_f_revocation_blocks_replay_and_cleans_connection(self):
  self.ready();import_verified_requirement_version(self.owner,'P1','B1','R1','V1','source:rv','r1')
  self.relations.attach_requirement_version('alice','P1','B1','R1','V1',3,'verified')
  self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
  self.error(403,lambda:self.relations.attach_requirement_version('alice','P1','B1','R1','V1',3,'verified'))
  self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
 def test_f_nonempty_downgrade_preserves_all(self):
  self.ready();import_verified_requirement_version(self.owner,'P1','B1','R1','V1','source:rv','r1')
  with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_BACKUP'):downgrade(self.owner,1)
  self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.verified_requirement_version').fetchone()[0],1)
  self.assertEqual(self.owner.execute('SELECT max(version) FROM public.wb_schema_migration').fetchone()[0],3)
