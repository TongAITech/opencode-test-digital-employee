"""B05 PostgreSQL SST authority and version-scoped source identity tests."""
import unittest
import test_dsh_workbench_b_relations_postgres as prior
from tools.dsh_workbench.business_migrations import migrate,downgrade
from tools.dsh_workbench.business_relations import import_sst_identity,import_verified_sst_link,import_verified_requirement_version

@unittest.skipUnless(prior.DSN and prior.psycopg,'real PostgreSQL DSN and psycopg required')
class SST(prior.RequirementVersion):
    def setUp(self):
        super().setUp()
        migrate(self.owner,target=4)
        for table in ['sst_identity','verified_sst_link']:
            self.owner.execute(prior.sql.SQL('GRANT SELECT ON wb.{} TO {}').format(prior.sql.Identifier(table),prior.sql.Identifier(self.role)))
        self.owner.execute(prior.sql.SQL('GRANT SELECT,INSERT ON wb.batch_requirement_version_sst TO {}').format(prior.sql.Identifier(self.role)))

    def sst_seed(self):
        self.seed()
        self.relations.attach_member('alice','P1','B1','requirement','R1',1,'ar')
        self.relations.attach_member('alice','P1','B1','version','V1',2,'av')
        import_verified_requirement_version(self.owner,'P1','B1','R1','V1','source:rv','r1')
        self.relations.attach_requirement_version('alice','P1','B1','R1','V1',3,'brv')
        import_sst_identity(self.owner,'P1','V1','SST1','src','prod','RAW-100','r1','source:sst1')

    def test_verified_brvs_exact_tuple_required_no_cross_requirement_inheritance(self):
        self.sst_seed()
        self.error(422,lambda:self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'missing-source'))
        import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST1','source:link1','r1')
        self.assertEqual(self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach'),5)
        self.assertEqual(self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach'),5)
        self.relations.create_requirement('alice','P1','R2','src','prod','r2','r1','source:r2','r2')
        self.relations.attach_member('alice','P1','B1','requirement','R2',5,'ar2')
        import_verified_requirement_version(self.owner,'P1','B1','R2','V1','source:rv2','r1')
        self.relations.attach_requirement_version('alice','P1','B1','R2','V1',6,'brv2')
        self.error(422,lambda:self.relations.attach_sst('alice','P1','B1','R2','V1','SST1',7,'no-inherit'))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version_sst').fetchone()[0],1)
        self.assertEqual(self.owner.execute('SELECT relation_revision FROM wb.release_batch').fetchone()[0],7)

    def test_same_raw_sst_across_versions_distinct_internal_ids(self):
        self.sst_seed()
        self.store.create_version('alice','P1','V2','S1','same','src','prod','v2','r1','v2')
        import_sst_identity(self.owner,'P1','V2','SST2','src','prod','RAW-100','r2','source:sst2')
        rows=self.owner.execute('SELECT version_id,sst_id,source_object_id FROM wb.sst_identity ORDER BY version_id').fetchall()
        self.assertEqual(rows,[('V1','SST1','RAW-100'),('V2','SST2','RAW-100')])
        for args in [('V1','DUP','RAW-100'),('V2','SST1','RAW-OTHER')]:
            with self.assertRaises(prior.psycopg.Error): import_sst_identity(self.owner,'P1',args[0],args[1],'src','prod',args[2],'r3','source:bad')
        # Existing legitimate SST in another version cannot satisfy V1's link.
        with self.assertRaises(prior.psycopg.Error): import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST2','wrong-version','r1')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.sst_identity').fetchone()[0],2)

    def test_runtime_cannot_forge_sources_or_rewrite_accepted_links(self):
        self.sst_seed()
        import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST1','source:link1','r1')
        self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach')
        for table in ['sst_identity','verified_sst_link','batch_requirement_version_sst']:
            with self.assertRaises(prior.psycopg.Error): self.owner.execute('DELETE FROM wb.'+table)
        with self.assertRaises(prior.psycopg.Error): self.owner.execute("UPDATE wb.sst_identity SET source_revision='silent'")
        with self.assertRaises(prior.psycopg.Error): import_sst_identity(self.runtime,'P1','V1','FORGED','src','prod','bad','r1','fake')
        self.error(403,lambda:self.relations.attach_sst('bob','P1','B1','R1','V1','SST1',5,'forbidden'))
        with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_BACKUP'): downgrade(self.owner,3)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version_sst').fetchone()[0],1)

    def test_sst_audit_failure_transaction_rollback_and_recovery(self):
        self.sst_seed()
        import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST1','source:link1','r1')
        self.owner.execute("CREATE FUNCTION wb.fail_sst_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='batch.sst' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.audit FOR EACH ROW EXECUTE FUNCTION wb.fail_sst_audit()')
        with self.assertRaises(prior.psycopg.Error): self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version_sst').fetchone()[0],0)
        self.assertEqual(self.owner.execute('SELECT relation_revision FROM wb.release_batch').fetchone()[0],4)
        self.owner.execute('DROP TRIGGER fail ON wb.audit')
        self.assertEqual(self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach'),5)

    def test_empty_sst_increment_downgrade_keeps_existing_brv(self):
        self.seed()
        downgrade(self.owner,3)
        self.assertIsNone(self.owner.execute("SELECT to_regclass('wb.sst_identity')").fetchone()[0])
        self.assertTrue(migrate(self.owner,target=4))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.requirement').fetchone()[0],1)

    def test_three_versions_multiple_ssts_keep_exact_requirement_edges(self):
        self.sst_seed()
        revision=4
        for index,version in enumerate(['V1','V2','V3'],1):
            if version!='V1':
                self.store.create_version('alice','P1',version,'S1','same','src','prod','raw-'+version,'r1','create-'+version)
                revision=self.relations.attach_member('alice','P1','B1','version',version,revision,'member-'+version)
                import_verified_requirement_version(self.owner,'P1','B1','R1',version,'source:rv-'+version,'r1')
                revision=self.relations.attach_requirement_version('alice','P1','B1','R1',version,revision,'brv-'+version)
            for offset in [1,2]:
                sst='SST1' if (index,offset)==(1,1) else 'SST-%d-%d'%(index,offset)
                if sst!='SST1': import_sst_identity(self.owner,'P1',version,sst,'src','prod','RAW-'+str(offset*100),'r1','source:'+sst)
                import_verified_sst_link(self.owner,'P1','B1','R1',version,sst,'source:link-'+sst,'r1')
                revision=self.relations.attach_sst('alice','P1','B1','R1',version,sst,revision,'attach-'+sst)
        self.assertEqual(self.owner.execute('SELECT version_id,count(*) FROM wb.batch_requirement_version_sst GROUP BY version_id ORDER BY version_id').fetchall(),[('V1',2),('V2',2),('V3',2)])
        self.assertEqual(self.owner.execute('SELECT count(DISTINCT sst_id) FROM wb.batch_requirement_version_sst').fetchone()[0],6)
