import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_postgres import PostgresIdentity
class FAttack(PostgresIdentity):
 def test_f_manual_outer_transaction_identity_leak(self):
  self.batch()
  self.runtime.execute('BEGIN')
  self.store.batches('alice','P1')
  identity=self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0]
  visible=self.runtime.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0]
  self.runtime.execute('ROLLBACK')
  self.assertEqual((identity,visible),('',0),'outer BEGIN retains alice identity and exposes rows after scoped call')
