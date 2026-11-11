import tempfile,threading,unittest,json
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from rc7_admin.product_server import ProductAdminApplication,create_server
class FMount(unittest.TestCase):
 def test_namespace_never_calls_legacy_dispatch_or_accepts_spoof(self):
  with tempfile.TemporaryDirectory() as root:
   app=ProductAdminApplication(str(Path(root)/'r1'));calls=[];original=app.dispatch_get
   def observe(path,q):calls.append(path);return original(path,q)
   app.dispatch_get=observe;s=create_server(app,port=0);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
   try:
    for path in ['/api/workbench/v1','/api/workbench/v1/','/api/workbench/v1/missions/secret/overview','/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope?principal=admin']:
     try:urlopen(Request('http://127.0.0.1:%s%s'%(s.server_port,path),headers={'X-Principal':'admin','Authorization':'Bearer admin'}),timeout=5)
     except HTTPError as e:self.assertEqual(e.code,503);self.assertEqual(json.load(e)['error']['code'],'HOST_IDENTITY_UNAVAILABLE')
     else:self.fail('unexpected ready')
    self.assertEqual(calls,[])
    with urlopen('http://127.0.0.1:%s/api/meta'%s.server_port) as r:self.assertEqual(r.status,200)
    self.assertEqual(calls,['/api/meta'])
   finally:s.shutdown();s.server_close();t.join()
