"""PostgreSQL B03 batch membership repository, separate from R1 facts."""
from .business_store import BusinessStore, BusinessError


class RelationStore(BusinessStore):
    def _revision(self,project,batch,expected):
        row=self.db.execute('SELECT relation_revision FROM wb.release_batch WHERE project_id=%s AND batch_id=%s FOR UPDATE',(project,batch)).fetchone()
        if row is None:
            raise BusinessError(404,'RESOURCE_NOT_FOUND')
        if row[0]!=expected:
            raise BusinessError(409,'RELATION_REVISION_CONFLICT')

    def _bump_revision(self,project,batch):
        # Schema005 derives revisions in DB triggers. Earlier reviewed schemas
        # retain the explicit transactional bump for backward compatibility.
        self.db.execute("UPDATE wb.release_batch SET relation_revision=relation_revision+1 WHERE project_id=%s AND batch_id=%s AND NOT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wb' AND c.relname='batch_requirement' AND t.tgname='relation_row_changed')",(project,batch))

    def create_requirement(self,principal,project,requirement,source,namespace,object_id,source_revision,source_ref,request):
        with self._scope(principal,project):
            payload=['requirement',requirement,source,namespace,object_id,source_revision,source_ref]
            if self._claim(project,principal,request,payload): return
            self.db.execute('INSERT INTO wb.requirement VALUES(%s,%s,%s,%s,%s,%s,%s)',(project,requirement,source,namespace,object_id,source_revision,source_ref))
            self._audit(project,principal,request,'requirement.create',requirement,{'source_ref':source_ref,'source_revision':source_revision})

    def attach_member(self,principal,project,batch,kind,member,expected,request):
        if kind not in ('requirement','version'):
            raise BusinessError(400,'INVALID_MEMBER_KIND')
        with self._scope(principal,project):
            if self._claim(project,principal,request,['member',batch,kind,member,expected]): return expected+1
            self._revision(project,batch,expected)
            # SQL identifier only from the two literal allowlisted choices above.
            self.db.execute('INSERT INTO wb.batch_'+kind+' VALUES(%s,%s,%s)',(project,batch,member))
            self._bump_revision(project,batch)
            self._audit(project,principal,request,'batch.member',batch,{'kind':kind,'id':member,'revision':expected+1})
            return expected+1

    def attach_requirement_version(self,principal,project,batch,requirement,version,expected,request):
        with self._scope(principal,project):
            if self._claim(project,principal,request,['brv',batch,requirement,version,expected]): return expected+1
            self._revision(project,batch,expected)
            self.db.execute('INSERT INTO wb.batch_requirement_version VALUES(%s,%s,%s,%s)',(project,batch,requirement,version))
            self._bump_revision(project,batch)
            self._audit(project,principal,request,'batch.requirement_version',batch,{'requirement':requirement,'version':version,'revision':expected+1})
            return expected+1

    def attach_sst(self,principal,project,batch,requirement,version,sst,expected,request):
        with self._scope(principal,project):
            if self._claim(project,principal,request,['brvs',batch,requirement,version,sst,expected]): return expected+1
            self._revision(project,batch,expected)
            self.db.execute('INSERT INTO wb.batch_requirement_version_sst VALUES(%s,%s,%s,%s,%s)',(project,batch,requirement,version,sst))
            self._bump_revision(project,batch)
            self._audit(project,principal,request,'batch.sst',batch,{'requirement':requirement,'version':version,'sst':sst,'revision':expected+1})
            return expected+1


def import_verified_requirement_version(owner_connection,project,batch,requirement,version,source_link_ref,source_revision):
    """Trusted source-ingestion owner only, after external proof verification.

    Runtime role cannot write this table. Do not expose as a client mutation.
    """
    with owner_connection.transaction():
        owner_connection.execute('INSERT INTO wb.verified_requirement_version VALUES(%s,%s,%s,%s,%s,%s)',(project,batch,requirement,version,source_link_ref,source_revision))
        owner_connection.execute("INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail) VALUES(%s,current_user,%s,'source.requirement_version',%s,jsonb_build_object('source_ref',%s::text,'source_revision',%s::text))",(project,source_link_ref+':'+source_revision,batch,source_link_ref,source_revision))


def import_sst_identity(owner_connection,project,version,sst,source,namespace,object_id,source_revision,source_ref):
    """Trusted, source-verified ingestion only; runtime has no INSERT privilege."""
    with owner_connection.transaction():
        owner_connection.execute('INSERT INTO wb.sst_identity VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(project,version,sst,source,namespace,object_id,source_revision,source_ref))
        owner_connection.execute("INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail) VALUES(%s,current_user,%s,'source.sst',%s,jsonb_build_object('source_ref',%s::text,'source_revision',%s::text,'version',%s::text))",(project,'sst:'+sst+':'+source_revision,sst,source_ref,source_revision,version))


def import_verified_sst_link(owner_connection,project,batch,requirement,version,sst,source_link_ref,source_revision):
    """External proof must authorize this exact requirement/version/SST tuple."""
    with owner_connection.transaction():
        owner_connection.execute('INSERT INTO wb.verified_sst_link VALUES(%s,%s,%s,%s,%s,%s,%s)',(project,batch,requirement,version,sst,source_link_ref,source_revision))
        owner_connection.execute("INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail) VALUES(%s,current_user,%s,'source.sst_link',%s,jsonb_build_object('source_ref',%s::text,'source_revision',%s::text,'sst',%s::text))",(project,'sst-link:'+source_link_ref+':'+source_revision,batch,source_link_ref,source_revision,sst))
