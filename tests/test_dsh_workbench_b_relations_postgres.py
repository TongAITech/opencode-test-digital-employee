"""B03 real PostgreSQL batch membership tests; no SQLite substitutes."""
import test_dsh_workbench_b_postgres as base
from test_dsh_workbench_b_postgres import DSN, psycopg
sql=getattr(base,'sql',None)
from tools.dsh_workbench.business_migrations import migrate, downgrade
from tools.dsh_workbench.business_relations import RelationStore, import_verified_requirement_version
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


@unittest.skipUnless(DSN and psycopg,'real PostgreSQL DSN and psycopg required')
class RequirementVersion(Membership):
    def setUp(self):
        super().setUp()
        migrate(self.owner,target=3)
        self.owner.execute(sql.SQL('GRANT SELECT ON wb.verified_requirement_version TO {}').format(sql.Identifier(self.role)))
        self.owner.execute(sql.SQL('GRANT SELECT,INSERT ON wb.batch_requirement_version TO {}').format(sql.Identifier(self.role)))

    def test_brv_source_whitelist_rejects_cartesian_pair_and_is_immutable(self):
        self.seed()
        self.relations.attach_member('alice','P1','B1','requirement','R1',1,'ar')
        self.relations.attach_member('alice','P1','B1','version','V1',2,'av')
        self.error(422,lambda:self.relations.attach_requirement_version('alice','P1','B1','R1','V1',3,'unverified'))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version').fetchone()[0],0)
        import_verified_requirement_version(self.owner,'P1','B1','R1','V1','source:rv','r1')
        self.assertEqual(self.relations.attach_requirement_version('alice','P1','B1','R1','V1',3,'verified'),4)
        self.relations.create_requirement('alice','P1','R2','src','prod','r2','r1','source:r2','r2')
        self.relations.attach_member('alice','P1','B1','requirement','R2',4,'ar2')
        self.error(422,lambda:self.relations.attach_requirement_version('alice','P1','B1','R2','V1',5,'cartesian'))
        with self.assertRaises(psycopg.Error): self.runtime.execute("INSERT INTO wb.verified_requirement_version VALUES('P1','B1','R2','V1','forged','r1')")
        with self.assertRaises(psycopg.Error): self.owner.execute("UPDATE wb.verified_requirement_version SET source_revision='silent-change'")
        with self.assertRaises(psycopg.Error): self.owner.execute('DELETE FROM wb.verified_requirement_version')
        self.assertEqual(self.owner.execute('SELECT source_revision FROM wb.verified_requirement_version').fetchone()[0],'r1')

    def test_incremental_empty_downgrade_preserves_existing_date_domain(self):
        self.batch()
        downgrade(self.owner,1)
        self.assertIsNone(self.owner.execute("SELECT to_regclass('wb.requirement')").fetchone()[0])
        self.assertEqual(self.store.reschedule('alice','P1','B1','2026-11-13',1,'after-down','reason','CHG'),2)
        self.assertTrue(migrate(self.owner,target=3))
        self.assertEqual(self.owner.execute('SELECT relation_revision FROM wb.release_batch').fetchone()[0],1)
