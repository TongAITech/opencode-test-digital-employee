"""B06 PostgreSQL verified Scope query with signed revision-bound pagination."""
import base64
import hashlib
import hmac
import json
from .business_store import BusinessStore,BusinessError


class ScopeStore(BusinessStore):
    def __init__(self,connection,cursor_key):
        super().__init__(connection)
        if not isinstance(cursor_key,bytes) or len(cursor_key)<32:
            raise ValueError('CURSOR_KEY_MINIMUM_32_BYTES')
        self.key=cursor_key

    def _encode(self,payload):
        body=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
        return base64.urlsafe_b64encode(body).decode().rstrip('=')+'.'+hmac.new(self.key,body,hashlib.sha256).hexdigest()

    def _decode(self,token):
        try:
            if not isinstance(token,str) or len(token)>8192: raise ValueError()
            body,signature=token.split('.')
            body=base64.b64decode(body+'='*(-len(body)%4),altchars=b'-_',validate=True)
            if not hmac.compare_digest(signature,hmac.new(self.key,body,hashlib.sha256).hexdigest()): raise ValueError()
            value=json.loads(body)
            if not isinstance(value,dict): raise ValueError()
            return value
        except (ValueError,TypeError,UnicodeError):
            raise BusinessError(409,'STALE_CURSOR')

    @staticmethod
    def _ids(values):
        if values is None:return []
        if not isinstance(values,(list,tuple)) or len(values)>100 or any(not isinstance(x,str) or not x.strip() or len(x)>256 for x in values):
            raise BusinessError(400,'INVALID_SCOPE')
        return sorted(set(values))

    def scope(self,principal,project,batch_id=None,release_date=None,requirement_ids=None,system_version_ids=None,sst_ids=None,page_size=100,page_cursor=None):
        filters=[self._ids(x) for x in (requirement_ids,system_version_ids,sst_ids)]
        if type(page_size) is not int or not 1<=page_size<=100:
            raise BusinessError(400,'INVALID_PAGE_SIZE')
        if batch_id is not None and (not isinstance(batch_id,str) or not batch_id.strip() or len(batch_id)>256):raise BusinessError(400,'INVALID_SCOPE')
        if not batch_id and not release_date:raise BusinessError(400,'INVALID_SCOPE')
        date=str(self._date(release_date)) if release_date else None
        with self._scope(principal,project,False,isolation='repeatable read'):
            access=self.db.execute('SELECT access_scope_revision FROM wb.project WHERE project_id=%s',(project,)).fetchone()[0]
            if batch_id:
                batch=self.db.execute('SELECT batch_id,release_date,relation_revision FROM wb.release_batch WHERE project_id=%s AND batch_id=%s',(project,batch_id)).fetchone()
            else:
                batch=self.db.execute('SELECT batch_id,release_date,relation_revision FROM wb.release_batch WHERE project_id=%s AND release_date=%s',(project,date)).fetchone()
            if batch is None:raise BusinessError(404,'RESOURCE_NOT_FOUND')
            batch_id,actual_date,revision=batch
            if date and date!=str(actual_date):
                raise BusinessError(409 if page_cursor is not None else 400,'STALE_CURSOR' if page_cursor is not None else 'INVALID_SCOPE')
            binding={'v':1,'principal':principal,'project':project,'batch':batch_id,'date':str(actual_date),'filters':filters,'relation_revision':revision,'access_scope_revision':access,'page_size':page_size}
            offset=0
            if page_cursor is not None:
                cursor=self._decode(page_cursor)
                offset=cursor.pop('offset',None)
                if cursor!=binding or type(offset) is not int or offset<1:raise BusinessError(409,'STALE_CURSOR')
            query=''' FROM wb.batch_requirement_version r
              JOIN wb.verified_requirement_version rv USING(project_id,batch_id,requirement_id,version_id)
              LEFT JOIN wb.batch_requirement_version_sst s USING(project_id,batch_id,requirement_id,version_id)
              LEFT JOIN wb.verified_sst_link l USING(project_id,batch_id,requirement_id,version_id,sst_id)
              WHERE r.project_id=%s AND r.batch_id=%s'''
            args=[project,batch_id]
            for ids,column in zip(filters,['r.requirement_id','r.version_id','s.sst_id']):
                if ids:
                    query+=' AND '+column+'=ANY(%s)'
                    args.append(ids)
            counts=self.db.execute('SELECT count(*),count(DISTINCT r.requirement_id),count(DISTINCT r.version_id),count(DISTINCT s.sst_id)'+query,args).fetchone()
            if not counts[0] or any(ids and len(ids)!=count for ids,count in zip(filters,counts[1:])):
                raise BusinessError(422,'ILLEGAL_ASSOCIATION')
            rows=self.db.execute('SELECT r.requirement_id,r.version_id,s.sst_id,rv.source_link_ref,rv.source_revision,l.source_link_ref,l.verified_source_revision'+query+' ORDER BY r.requirement_id,r.version_id,s.sst_id NULLS FIRST LIMIT %s OFFSET %s',args+[page_size+1,offset]).fetchall()
            if not rows:raise BusinessError(409,'STALE_CURSOR')
            records=[];sources=set()
            for requirement,version,sst,rv_ref,rv_revision,link_ref,link_revision in rows[:page_size]:
                if not rv_ref or (sst is not None and not link_ref):raise BusinessError(503,'SOURCE_PROOF_UNAVAILABLE')
                sources.add(rv_ref)
                if link_ref:sources.add(link_ref)
                records.append({'requirement_id':requirement,'system_version_id':version,'sst_id':sst,'split_state':'UNSPLIT' if sst is None else 'SPLIT','source_verified_requirement_version':{'source_link_ref':rv_ref,'source_revision':rv_revision},'source_verified_link':None if sst is None else {'source_link_ref':link_ref,'verified_source_revision':link_revision}})
            next_cursor=None
            if len(rows)>page_size:next_cursor=self._encode(dict(binding,offset=offset+page_size))
            return {'project_id':project,'batch_id':batch_id,'release_date':str(actual_date),'relation_revision':revision,'access_scope_revision':access,'records':records,'source_refs':sorted(sources),'warnings':[],'gap_indicators':[],'next_page_cursor':next_cursor}
