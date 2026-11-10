import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_postgres import PostgresIdentity
class FRecheck(PostgresIdentity):
 def test_f_explicit_begin_rejected_without_identity(self):
  self.batch();self.runtime.execute('BEGIN')
  with self.assertRaisesRegex(ValueError,'IDLE_CONNECTION_REQUIRED'):
   self.store.batches('alice','P1')
  self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
  self.assertEqual(self.runtime.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],0)
  self.runtime.execute('ROLLBACK')
  self.assertEqual(len(self.store.batches('alice','P1')),1)
