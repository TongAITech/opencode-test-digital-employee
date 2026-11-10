"""PostgreSQL B03 batch membership repository, separate from R1 facts."""
from .business_store import BusinessStore, BusinessError


class RelationStore(BusinessStore):
    def _revision(self,project,batch,expected):
        row=self.db.execute('SELECT relation_revision FROM wb.release_batch WHERE project_id=%s AND batch_id=%s FOR UPDATE',(project,batch)).fetchone()
        if row is None:
            raise BusinessError(404,'RESOURCE_NOT_FOUND')
        if row[0]!=expected:
            raise BusinessError(409,'RELATION_REVISION_CONFLICT')

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
            self.db.execute('UPDATE wb.release_batch SET relation_revision=relation_revision+1 WHERE project_id=%s AND batch_id=%s',(project,batch))
            self._audit(project,principal,request,'batch.member',batch,{'kind':kind,'id':member,'revision':expected+1})
            return expected+1
