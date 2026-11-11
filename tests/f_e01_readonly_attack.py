import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_e01_postgres import E01
from rc7_admin.projection import AdminProjection
from tools.dsh_workbench.e01_service import E01Service
from unittest.mock import patch
class FAttack(E01):
 def test_f_revocation_during_r1_read_denies_result_and_preserves_bytes(self):
  self.scope_seed();self.setup_r1();owner=self.owner
  class RevokeAfterRead(AdminProjection):
   def mission_overview_scoped(self,*args,**kwargs):
    result=super().mission_overview_scoped(*args,**kwargs)
    owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
    return result
  with patch('tools.dsh_workbench.e01_service.AdminProjection',RevokeAfterRead):
   self.error(403,lambda:E01Service(self.scope,self.r1,self.root).quality('alice','P1','B1','2026-11-12','M1'))
  self.assertEqual(self.before,self.r1.read_bytes())
 def test_f_missing_r1_never_created(self):
  self.scope_seed();self.setup_r1();missing=self.root/'nonexistent.jsonl'
  self.error(503,lambda:E01Service(self.scope,missing,self.root).quality('alice','P1','B1','2026-11-12','M1'))
  self.assertFalse(missing.exists());self.assertEqual(self.before,self.r1.read_bytes())
