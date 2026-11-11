"""Real PostgreSQL, loopback HTTP and persisted synthetic R1 component tests."""
import hashlib
import tempfile
from pathlib import Path
from dataclasses import asdict
import threading
import unittest
from unittest.mock import patch
from rc7_admin.projection import AdminProjection
import test_dsh_workbench_b_scope_postgres as prior
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence, Mission
from tools.dsh_workbench.business_http import create_scope_server,HostIdentity
from tools.dsh_workbench.e01_service import E01Service

@unittest.skipUnless(prior.prior.prior.DSN and prior.prior.prior.psycopg,'real PG required')
class E01(prior.Scope):
    def setup_r1(self, bound=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.r1=self.root/'r1.jsonl'
        runtime=TruthRuntime(self.r1)
        payload=asdict(Mission(mission_id='M1',release_id='B1',goal='synthetic component fixture'))
        if bound:payload.update(project_id='P1',batch_id='B1')
        runtime.append_atomic('RC7_MISSION_UPSERTED',payload)
        self.before=self.r1.read_bytes()

    def quality_server(self,provider='fixture'):
        if provider=='fixture':provider=lambda request:HostIdentity('alice') if request.headers.get('Authorization')=='Bearer host-test-token' else None
        server=create_scope_server(('127.0.0.1',0),lambda:prior.prior.prior.psycopg.connect(**self.params,autocommit=True),self.scope.key,provider,lambda scope:E01Service(scope,self.r1,self.root))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery(self):
        self.scope_seed();self.setup_r1();origin=self.quality_server()
        path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/quality?batch_id=B1&mission_id=M1&page_size=1'
        status,value=self.http(origin,path)
        self.assertEqual(status,200,value);self.assertTrue(value['scope_complete'])
        self.assertEqual(value['truth_revision'],'sha256:'+hashlib.sha256(self.before).hexdigest())
        self.assertIsNotNone(value['as_of']);self.assertEqual(value['release_decision'],'HOLD')
        self.assertIn('EVIDENCE_MISSING',value['gap_indicators'])
        self.assertEqual(self.http(origin,path,False)[0],403)
        self.assertEqual(self.http(origin,path+'&principal=alice')[0],400)
        self.assertEqual(self.http(origin,path.replace('M1','missing'))[0],403)
        self.assertEqual(self.http(self.quality_server(None),path)[0],503)
        self.assertEqual(self.before,self.r1.read_bytes())
        self.r1.rename(self.root/'saved');self.assertEqual(self.http(origin,path)[0],503)
        (self.root/'saved').rename(self.r1);self.assertEqual(self.http(self.quality_server(),path)[0],200)
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.assertEqual(self.http(origin,path)[0],403)
        self.assertEqual(self.before,self.r1.read_bytes())

    def test_e01_rechecks_access_after_evidence_integrity_read(self):
        self.scope_seed()
        self.setup_r1()
        evidence = self.root / 'evidence.bin'
        evidence.write_bytes(b'controlled component evidence')
        record = Evidence(evidence_id='E1', mission_id='M1', kind='fixture',
                          source_ref='test-fixture', content_ref=evidence.as_uri(),
                          content_hash='sha256:' + hashlib.sha256(evidence.read_bytes()).hexdigest())
        TruthRuntime(self.r1).append_atomic('RC7_EVIDENCE_UPSERTED', dict(release_id='B1', **asdict(record)))
        before = self.r1.read_bytes()
        origin = self.quality_server()
        path = '/api/workbench/v1/projects/P1/release-dates/2026-11-12/quality?batch_id=B1&mission_id=M1'
        status, value = self.http(origin, path)
        self.assertEqual(status, 200, value)
        self.assertEqual(value['evidence'][0]['integrity'], 'HASH_VERIFIED_ONLY')

        original = E01Service._evidence

        def read_and_downgrade(service, row):
            result = original(service, row)
            self.owner.execute("UPDATE wb.project_acl SET can_write=false WHERE principal='alice'")
            return result

        with patch.object(E01Service, '_evidence', read_and_downgrade):
            status, value = self.http(origin, path)
        self.assertEqual(status, 409, value)
        self.assertNotIn('evidence', value)
        self.assertEqual(self.http(origin, path)[0], 200)

        checked = []

        def read_and_revoke(service, row):
            result = original(service, row)
            checked.append(result['integrity'])
            self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
            return result

        with patch.object(E01Service, '_evidence', read_and_revoke):
            status, value = self.http(origin, path)
        self.assertEqual(checked, ['HASH_VERIFIED_ONLY'])
        self.assertEqual(status, 403, value)
        self.assertNotIn('evidence', value)
        self.assertEqual(self.r1.read_bytes(), before)

    def test_e01_legacy_binding_rejected_and_partial_r1_fails_closed(self):
        self.scope_seed();self.setup_r1(False);origin=self.quality_server()
        path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/quality?batch_id=B1&mission_id=M1'
        calls=[]
        class ObservedProjection(AdminProjection):
            def __init__(self, truth):
                original=truth.query
                def query(kind,**filters):
                    calls.append(kind)
                    return original(kind,**filters)
                truth.query=query
                super().__init__(truth)
        with patch('tools.dsh_workbench.e01_service.AdminProjection',ObservedProjection):
            self.assertEqual(self.http(origin,path)[0],403)
        self.assertEqual(calls,['rc7_mission'])
        self.r1.write_bytes(self.before+b'{truncated')
        self.assertEqual(self.http(origin,path)[0],503)
        self.assertEqual(self.r1.read_bytes(),self.before+b'{truncated')

class Integrity(unittest.TestCase):
    def test_controlled_content_hash_missing_tamper_and_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/'evidence';file.write_bytes(b'actual')
            service=E01Service(None,root/'r1',root)
            row={'evidence_id':'E1','content_ref':file.as_uri(),'content_hash':'sha256:'+hashlib.sha256(b'actual').hexdigest()}
            self.assertEqual(service._evidence(row)['integrity'],'HASH_VERIFIED_ONLY')
            file.write_bytes(b'tampered');self.assertEqual(service._evidence(row)['integrity'],'HASH_MISMATCH')
            link=root/'escape';link.symlink_to('/etc/passwd')
            row['content_ref']=link.as_uri();self.assertEqual(service._evidence(row)['integrity'],'CONTENT_UNAVAILABLE')
            row['content_ref']='file:///etc/passwd';self.assertEqual(service._evidence(row)['integrity'],'CONTENT_UNAVAILABLE')
            row['content_ref']='https://example.test/private';self.assertEqual(service._evidence(row)['integrity'],'CONTENT_UNAVAILABLE')
