import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_mount_auth import MountedAuth
from unittest.mock import Mock
class FAttack(MountedAuth):
 def test_f_all_private_method_variants_no_dispatch(self):
  origin=self.start(True);self.app.dispatch_get=Mock(side_effect=AssertionError('legacy read'));self.app.dispatch_post=Mock(side_effect=AssertionError('legacy write'))
  for method in ['GET','POST','PUT','DELETE','PATCH']:
   status,body=self.call(origin,'/api/missions/M_FOREIGN/overview',method,b'{invalid' if method!='GET' else None)
   self.assertIn(status,(403,405));self.assertNotIn(b'private fixture',body)
  self.app.dispatch_get.assert_not_called();self.app.dispatch_post.assert_not_called();self.assertEqual(self.path.read_bytes(),self.before)
