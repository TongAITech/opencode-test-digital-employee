import unittest
import test_dsh_workbench_b_postgres as infra
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.business_directory import DirectoryStore

@unittest.skipUnless(infra.DSN and infra.psycopg,'real PostgreSQL required')
class Directory(infra.PostgresIdentity):
    def setUp(self):
        super().setUp();migrate(self.owner,target=5)
        self.directory=DirectoryStore(self.runtime,b'directory-test-key-at-least-32-bytes')
    def test_authorized_projects_empty_and_grant_revoke_cursor(self):
        self.assertEqual([r['project_id'] for r in self.directory.directory('alice')['records']],['P1'])
        self.assertEqual(self.directory.directory('nobody')['records'],[])
        self.owner.execute("INSERT INTO wb.project_acl VALUES('P2','alice',true)")
        first=self.directory.directory('alice',page_size=1)
        self.assertIsNone(self.directory.directory('alice',page_size=1,page_cursor=first['next_page_cursor'])['next_page_cursor'])
        self.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P2' AND principal='alice'")
        self.error(409,lambda:self.directory.directory('alice',page_size=1,page_cursor=first['next_page_cursor']))
    def test_dates_stable_identity_reschedule_and_denial(self):
        self.assertEqual(self.directory.directory('alice','P1')['records'],[])
        self.error(403,lambda:self.directory.directory('bob','P1'))
        self.batch();self.batch('B2','2026-11-19','c2')
        first=self.directory.directory('alice','P1',page_size=1)
        self.store.reschedule('alice','P1','B1','2026-11-13',1,'move','reason','approval')
        self.error(409,lambda:self.directory.directory('alice','P1',page_size=1,page_cursor=first['next_page_cursor']))
        self.assertEqual(self.directory.directory('alice','P1')['records'][0]['batch_id'],'B1')
    def test_real_http_auth_arrays_rejection_and_missing_host_database(self):
        import json,threading
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from tools.dsh_workbench.business_http import create_scope_server,HostIdentity
        def serve(factory,provider):
            server=create_scope_server(('127.0.0.1',0),factory,self.directory.key,provider)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            return 'http://127.0.0.1:'+str(server.server_port)
        def get(origin,path,token=True):
            try:
                with urlopen(Request(origin+path,headers={'Authorization':'fixture'} if token else {}),timeout=5) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        provider=lambda request:HostIdentity('alice') if request.headers.get('Authorization')=='fixture' else None
        factory=lambda:infra.psycopg.connect(**self.params,autocommit=True)
        origin=serve(factory,provider);path='/api/workbench/v1/projects'
        self.assertEqual(get(origin,path)[1]['records'][0]['name'],'first')
        self.assertEqual(get(origin,path,False)[0],403)
        self.assertEqual(get(origin,path+'?principal=bob')[0],400)
        self.assertEqual(get(origin,path+'?page_size=1&page_size=2')[0],400)
        self.assertEqual(get(origin,path+'/P2/release-dates')[0],403)
        self.assertEqual(get(origin,path+'/P1/release-dates')[1]['records'],[])
        self.assertEqual(get(serve(factory,None),path)[0],503)
        self.assertEqual(get(serve(lambda:(_ for _ in ()).throw(ConnectionError()),provider),path)[0],503)
        self.assertEqual(get(origin,path)[0],200)
