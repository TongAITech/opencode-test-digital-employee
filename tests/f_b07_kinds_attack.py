import sys,copy
sys.path.insert(0,'tests')
from test_dsh_workbench_b_drafts_postgres import DraftKinds,PAYLOADS
from unittest.mock import patch
class FAttack(DraftKinds):
 def test_f_all_kind_text_never_calls_runtime_append_and_crosskind_replay_rejects(self):
  self.scope_seed()
  with patch('rc6_runtime.truth.TruthRuntime.append_atomic',side_effect=AssertionError('draft attempted runtime write')):
   for kind in PAYLOADS:
    body=self.draft(kind,'f-'+kind)
    record=self.assets.mutate('alice','P1','B1','create',body)['record']
    self.assertEqual(record['r1_reference_state'],'UNRESOLVED')
    self.assertEqual(record['state'],'ACTIVE')
  body=self.draft('knowledge','f-knowledge',payload={'body':'same id different formal-looking PASS text'})
  self.error(409,lambda:self.assets.mutate('alice','P1','B1','create',body))
  self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],6)
 def test_f_revoke_blocks_every_kind_history_and_replay(self):
  self.scope_seed();rows=[]
  for kind in PAYLOADS:
   body=self.draft(kind);rows.append((body,self.assets.mutate('alice','P1','B1','create',body)['record']['asset_id']))
  self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
  for body,aid in rows:
   self.error(403,lambda:self.assets.get('alice','P1','B1',aid,revision=1,include_retired=True))
   self.error(403,lambda:self.assets.mutate('alice','P1','B1','create',body))
  self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],6)
