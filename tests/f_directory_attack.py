import sys
sys.path.insert(0,'tests')
from test_dsh_workbench_b_directory_postgres import Directory
class FAttack(Directory):
 def test_f_cross_subject_cursor_and_renamed_project_stale(self):
  self.owner.execute("INSERT INTO wb.project_acl VALUES('P2','alice',true),('P1','bob',true)")
  page=self.directory.directory('alice',page_size=1);cursor=page['next_page_cursor']
  self.error(409,lambda:self.directory.directory('bob',page_size=1,page_cursor=cursor))
  self.owner.execute("UPDATE wb.project SET name='renamed' WHERE project_id='P1'")
  self.error(409,lambda:self.directory.directory('alice',page_size=1,page_cursor=cursor))
  self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
 def test_f_dates_cursor_regrant_and_unknown_project_never_leaks(self):
  self.batch();self.batch('B2','2026-11-19','c2')
  cursor=self.directory.directory('alice','P1',page_size=1)['next_page_cursor']
  self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
  self.error(403,lambda:self.directory.directory('alice','P1',page_size=1,page_cursor=cursor))
  self.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
  self.error(409,lambda:self.directory.directory('alice','P1',page_size=1,page_cursor=cursor))
  self.error(403,lambda:self.directory.directory('bob','nonexistent'))
