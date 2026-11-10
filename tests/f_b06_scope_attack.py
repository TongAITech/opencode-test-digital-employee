import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_scope_postgres import Scope
class FAttack(Scope):
 def test_f_revoke_regrant_stales_cursor_and_filter_binding(self):
  self.scope_seed();cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
  self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
  self.error(403,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor))
  self.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
  self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor))
  cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
  self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor,requirement_ids=['R1','R2']))
  self.assertEqual(len(self.scope.scope('alice','P1','B1')['records']),2)
 def test_f_http_body_or_headers_do_not_supply_identity(self):
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  self.scope_seed();origin=self.start_server();path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope'
  for headers,body in [({'X-Principal':'alice'},None),({'Content-Type':'application/json'},b'{"principal":"alice"}')]:
   try:urlopen(Request(origin+path,data=body,headers=headers,method='GET'),timeout=5)
   except HTTPError as e:self.assertEqual(e.code,403)
   else:self.fail('spoof accepted')
  self.assertEqual(self.http(origin,path)[0],200)
