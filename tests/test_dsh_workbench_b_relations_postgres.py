"""B03 real PostgreSQL batch membership tests; no SQLite substitutes."""
import test_dsh_workbench_b_postgres as base
from test_dsh_workbench_b_postgres import DSN, psycopg, sql
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.business_relations import RelationStore
import unittest

@unittest.skipUnless(DSN and psycopg,'real PostgreSQL DSN and psycopg required')
class Membership(base.PostgresIdentity):
    def setUp(self):
        super().setUp()
        migrate(self.owner,target=2)
        for table in ['requirement','batch_requirement','batch_version']:
            self.owner.execute(sql.SQL('GRANT SELECT,INSERT ON wb.{} TO {}').format(sql.Identifier(table),sql.Identifier(self.role)))
        self.relations=RelationStore(self.runtime)

    def seed(self):
        self.batch()
        self.store.create_system('alice','P1','S1','src','prod','sys1','r1','s1')
        self.store.create_version('alice','P1','V1','S1','same','src','prod','v1','r1','v1')
        self.relations.create_requirement('alice','P1','R1','src','prod','r1','r1','source:r1','r1')

    def test_membership_scope_revision_replay_and_cross_project_reject(self):
        self.seed()
        self.assertEqual(self.relations.attach_member('alice','P1','B1','requirement','R1',1,'attach-r'),2)
        self.assertEqual(self.relations.attach_member('alice','P1','B1','requirement','R1',1,'attach-r'),2)
        self.assertEqual(self.relations.attach_member('alice','P1','B1','version','V1',2,'attach-v'),3)
        self.error(409,lambda:self.relations.attach_member('alice','P1','B1','version','V1',1,'stale'))
        self.store.create_batch('bob','P2','B2','2026-11-12','b2')
        self.error(422,lambda:self.relations.attach_member('bob','P2','B2','version','V1',1,'cross'))
        self.assertEqual(self.owner.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P2'").fetchone()[0],1)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_version').fetchone()[0],1)

    def test_membership_audit_failure_rolls_back_relation_and_revision(self):
        self.seed()
        self.owner.execute("CREATE FUNCTION wb.fail_member_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='batch.member' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.audit FOR EACH ROW EXECUTE FUNCTION wb.fail_member_audit()')
        with self.assertRaises(psycopg.Error): self.relations.attach_member('alice','P1','B1','version','V1',1,'attach')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_version').fetchone()[0],0)
        self.assertEqual(self.owner.execute('SELECT relation_revision FROM wb.release_batch').fetchone()[0],1)
        self.owner.execute('DROP TRIGGER fail ON wb.audit')
        self.assertEqual(self.relations.attach_member('alice','P1','B1','version','V1',1,'attach'),2)
