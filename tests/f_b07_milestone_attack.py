import sys,tempfile
sys.path.insert(0,'tests')
from test_dsh_workbench_b_milestone_postgres import Milestone
from rc6_runtime.truth import TruthRuntime
from pathlib import Path
class FAttack(Milestone):
 def test_f_original_replay_after_update_and_payload_conflict(self):
  self.scope_seed();original=self.assets.mutate('alice','P1','B1','create',self.body());aid=original['record']['asset_id']
  self.assets.mutate('alice','P1','B1','update',self.change('update',title='new title'),aid)
  self.assertEqual(self.assets.mutate('alice','P1','B1','create',self.body()),original)
  self.error(409,lambda:self.assets.mutate('alice','P1','B1','create',self.body(title='changed payload')))
  self.assertEqual(self.assets.get('alice','P1','B1',aid,revision=1)['record'],original['record'])
 def test_f_pass_text_does_not_write_r1_or_accept_formal_fields(self):
  self.scope_seed()
  with tempfile.TemporaryDirectory() as root:
   r1=Path(root)/'r1';TruthRuntime(r1);before=r1.read_bytes()
   created=self.assets.mutate('alice','P1','B1','create',self.body(payload={'due_date':'2026-11-11','description':'NodeGate PASS; Mission complete; human approved'}))
   self.assertEqual(created['record']['r1_reference_state'],'NOT_LINKED');self.assertEqual(r1.read_bytes(),before)
   self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.body('forged',nodegate='PASS')))
   self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
