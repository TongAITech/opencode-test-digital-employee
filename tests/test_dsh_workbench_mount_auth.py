"""Mounted workbench cannot fall through to unauthenticated legacy R1 APIs."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import Mock
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import scope_handler
from rc7_runtime.models import Mission
from rc7_runtime.truth_overlay import append_entity

class MountedAuth(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'r1';self.app=ProductAdminApplication(str(self.path))
        append_entity(self.app.truth,Mission(mission_id='M_FOREIGN',release_id='B2',goal='private fixture'),release_id='B2')
        self.before=self.path.read_bytes()
    def start(self,mounted,mode=False):
        kwargs={'workbench_handler':scope_handler(None,b'fixture-key-32-bytes-only-test!!',lambda request:None)} if mounted else {}
        server=create_server(self.app,port=0,workbench_mode=mode,**kwargs)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)
    def call(self,origin,path,method='GET',data=None):
        try:
            with urlopen(Request(origin+path,method=method,data=data),timeout=3) as response:return response.status,response.read()
        except HTTPError as error:return error.code,error.read()
    def test_mounted_private_get_post_block_before_dispatch_and_body_parse(self):
        origin=self.start(True)
        get=self.app.dispatch_get=Mock(wraps=self.app.dispatch_get)
        post=self.app.dispatch_post=Mock(side_effect=AssertionError('private write dispatched'))
        for path in ['/api/health','/api/missions/M_FOREIGN/overview','/api/test-cases','/api/requirement-hierarchy','/api/meta/','/api//meta','/api/../health','/api/missions/%4d_FOREIGN/overview']:
            with self.subTest(path=path):
                status,body=self.call(origin,path);self.assertEqual(status,403);self.assertNotIn(b'private fixture',body);self.assertNotIn(str(self.path).encode(),body)
        self.assertEqual(get.call_count,0)
        for path in ['/api/test-cases','/api/meta','/api/health']:
            self.assertEqual(self.call(origin,path,'POST',b'{malformed')[0],403)
        post.assert_not_called();get.assert_not_called()
        self.assertEqual(self.call(origin,'/api/meta')[0],200)
        self.assertEqual(get.call_count,1)
        self.assertEqual(self.call(origin,'/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope')[0],403)
        self.assertEqual(self.before,self.path.read_bytes())
    def test_standalone_legacy_mode_retains_existing_reads(self):
        origin=self.start(False)
        status,body=self.call(origin,'/api/missions/M_FOREIGN/overview')
        self.assertEqual(status,200);self.assertIn(b'M_FOREIGN',body)
        self.assertEqual(self.call(origin,'/api/health')[0],200)
        self.assertEqual(self.before,self.path.read_bytes())

    def test_explicit_workbench_mode_without_provider_fails_closed(self):
        origin=self.start(False,True)
        self.assertEqual(self.call(origin,'/api/health')[0],403)
        self.assertEqual(self.call(origin,'/api/meta')[0],200)
        self.assertEqual(self.call(origin,'/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope')[0],503)
    def test_cli_workbench_flag_enables_safe_mode(self):
        from unittest.mock import patch
        from rc7_admin.product_server import main
        server=Mock();server.server_address=("127.0.0.1",0);server.serve_forever.side_effect=KeyboardInterrupt()
        with patch('rc7_admin.product_server.create_server',return_value=server) as create:
            self.assertEqual(main(['--r1',str(self.path),'--port','0','--workbench']),0)
            self.assertTrue(create.call_args.kwargs['workbench_mode'])
        missing=self.path.parent/'not-created'/'missing-r1'
        with patch('rc7_admin.product_server.create_server',return_value=server),patch('builtins.print') as printed:
            self.assertEqual(main(['--r1',str(missing),'--workbench']),0)
            self.assertNotIn(str(missing),str(printed.call_args))
        self.assertFalse(missing.parent.exists())

    def test_real_postgres_authorized_workbench_still_reads(self):
        import test_dsh_workbench_e01_postgres as fixture
        from tools.dsh_workbench.e01_service import E01Service
        from tools.dsh_workbench.business_http import HostIdentity
        if not fixture.prior.prior.prior.DSN or not fixture.prior.prior.prior.psycopg:self.skipTest('real PG required')
        db=fixture.E01(methodName='test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery');db.setUp();self.addCleanup(db.doCleanups)
        db.scope_seed();db.setup_r1()
        handler=scope_handler(lambda:fixture.prior.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,lambda req:HostIdentity('alice'),lambda store:E01Service(store,db.r1,db.root))
        server=create_server(ProductAdminApplication(str(db.r1)),port=0,workbench_handler=handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin='http://127.0.0.1:'+str(server.server_port)
        path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/'
        self.assertEqual(self.call(origin,path+'scope?batch_id=B1')[0],200)
        self.assertEqual(self.call(origin,path+'quality?batch_id=B1&mission_id=M1')[0],200)
        self.assertEqual(self.call(origin,'/api/missions/M1/overview')[0],403)
        self.assertEqual(db.before,db.r1.read_bytes())
