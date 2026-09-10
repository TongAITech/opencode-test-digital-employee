"""Actual R1 and OS-process crash/concurrency checks; transport is a labeled file fixture."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,unittest
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from progress_regression import request
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.dispatch_receipts import dispatch_context,ContextDeliveryUnconfirmed

class ReceiptTransport(FakeOpenCodeSessionProvider):
    def __init__(self,root,fault=None):super().__init__(root);self.root=Path(root);self.fault=fault
    def send_context(self,*,session_id,agent,text):
        if self.fault=='before':os._exit(73)
        fd=os.open(self.root/'transport.jsonl',os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
        try:os.write(fd,(json.dumps({'session':session_id,'sha256':hashlib.sha256(text.encode()).hexdigest()})+'\n').encode())
        finally:os.close(fd)
        if self.fault=='after':os._exit(74)
        if self.fault=='exception':raise ConnectionError('INJECTED_AFTER_TRANSPORT_ACCEPTED')
        return {'accepted':True,'fixture':'FILE_TRANSPORT_ONLY'}

def service(root,fault=None):
    runtime=create_canonical_runtime(root,db_path=root/'spine.db')
    return G21AutonomousOrchestrationService(runtime,root,session_provider=ReceiptTransport(root,fault))
def send(root,fault=None):
    data=json.loads((root/'identity.json').read_text());s=service(root,fault)
    text='SYNTHETIC JOURNAL TEST\n'+json.dumps({'mission_id':data['mission_id']})
    return dispatch_context(s,session_id=data['session_id'],agent='aitest-planner',text=text,mode='AUTO_CONTINUE')
def lines(root):return (root/'transport.jsonl').read_text().splitlines()
def setup(root):
    s=service(root);start=s.start_test(request('journal'));mid=start['intake']['intake']['mission_id']
    sid=s.runtime.get_state(mid).sessions[-1].session_id
    (root/'identity.json').write_text(json.dumps({'mission_id':mid,'session_id':sid}))
    return s,mid

class JournalTests(unittest.TestCase):
    def test_four_independent_process_claims_send_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s,mid=setup(root)
            ps=[subprocess.Popen([sys.executable,__file__,'--send',d]) for _ in range(4)]
            self.assertEqual([p.wait(timeout=30) for p in ps],[0]*4)
            self.assertEqual(len(lines(root)),2) # one initial prompt, one wake
            fresh=service(root);records=fresh.session_control.state(mid).context_dispatches
            self.assertEqual(len(records),2);self.assertTrue(all(r['phase']=='ACCEPTED' for r in records))
            self.assertTrue(fresh.runtime.verify_projection(mid)['ok'])
    def test_real_process_death_never_blindly_reissues(self):
        for fault,exitcode,effects in [('before',73,1),('after',74,2)]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                root=Path(d);s,mid=setup(root)
                p=subprocess.run([sys.executable,__file__,'--send',d,fault],timeout=30)
                self.assertEqual(p.returncode,exitcode)
                with self.assertRaises(ContextDeliveryUnconfirmed):send(root)
                self.assertEqual(len(lines(root)),effects)
                fresh=service(root);self.assertEqual(fresh.session_control.state(mid).context_dispatches[-1]['phase'],'CLAIMED')
                self.assertTrue(fresh.runtime.verify_projection(mid)['ok'])
    def test_ambiguous_exception_is_durable_and_fenced(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s,mid=setup(root)
            with self.assertRaises(ContextDeliveryUnconfirmed):send(root,'exception')
            with self.assertRaises(ContextDeliveryUnconfirmed):send(root)
            self.assertEqual(len(lines(root)),2)
            self.assertEqual(service(root).session_control.state(mid).context_dispatches[-1]['phase'],'UNKNOWN')
    def test_changed_claim_identity_rejected_without_event(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s,mid=setup(root)
            with self.assertRaises(ContextDeliveryUnconfirmed):send(root,'exception')
            fresh=service(root);r=dict(fresh.session_control.state(mid).context_dispatches[-1]);r.pop('recorded_seq');r.pop('recorded_at')
            r.update(phase='ACCEPTED',context_digest='f'*64);head=fresh.runtime.get_head_seq(mid)
            with self.assertRaises(Exception):fresh.session_control.record_context_dispatch(mid,r)
            self.assertEqual(fresh.runtime.get_head_seq(mid),head)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--send':send(Path(sys.argv[2]),sys.argv[3] if len(sys.argv)>3 else None)
    else:unittest.main(verbosity=2)
