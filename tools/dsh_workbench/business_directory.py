"""Authorized business directories. No statistics, board phases or R1 facts."""
import hashlib
import json
from .business_scope import ScopeStore
from .business_store import BusinessError

class DirectoryStore(ScopeStore):
    def directory(self,principal,project=None,page_size=100,page_cursor=None):
        if type(page_size) is not int or not 1<=page_size<=100:raise BusinessError(400,'INVALID_PAGE_SIZE')
        if not isinstance(principal,str) or not principal.strip():raise BusinessError(403,'FORBIDDEN')
        if self.db.closed:raise BusinessError(503,'BUSINESS_DATABASE_UNAVAILABLE')
        if self.db.info.transaction_status!=0:raise ValueError('IDLE_CONNECTION_REQUIRED')
        try:
            with self.db.transaction():
                self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.db.execute("SELECT set_config('wb.principal',%s,true)",(principal,))
                if project is None:
                    rows=self.db.execute('SELECT project_id,name,access_scope_revision FROM wb.project ORDER BY project_id').fetchall()
                    records=[dict(zip(['project_id','name','access_scope_revision'],row)) for row in rows]
                else:
                    if not self.db.execute('SELECT wb.allowed(%s,false)',(project,)).fetchone()[0]:raise BusinessError(403,'FORBIDDEN')
                    access=self.db.execute('SELECT access_scope_revision FROM wb.project WHERE project_id=%s',(project,)).fetchone()[0]
                    rows=self.db.execute('SELECT batch_id,release_date,revision,relation_revision FROM wb.release_batch WHERE project_id=%s ORDER BY release_date,batch_id',(project,)).fetchall()
                    records=[{'project_id':project,'batch_id':r[0],'release_date':str(r[1]),'date_revision':r[2],'relation_revision':r[3],'access_scope_revision':access} for r in rows]
                snapshot={'records':records}
                if project is not None:snapshot['access_scope_revision']=access
                digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                binding={'type':'business-directory/v1','principal':principal,'project_id':project,'directory_revision':digest,'page_size':page_size}
                offset=0
                if page_cursor is not None:
                    cursor=self._decode(page_cursor);offset=cursor.pop('offset',None)
                    if cursor!=binding or type(offset) is not int or offset<1:raise BusinessError(409,'STALE_CURSOR')
                    if offset>=len(records):raise BusinessError(409,'STALE_CURSOR')
                next_cursor=self._encode(dict(binding,offset=offset+page_size)) if offset+page_size<len(records) else None
                result={'schema':'dsh-workbench/business-directory/v1','directory_revision':digest,'records':records[offset:offset+page_size],'next_page_cursor':next_cursor,'warnings':[],'gap_indicators':[]}
                if project is not None:result.update(project_id=project,access_scope_revision=access)
                return result
        except BusinessError:raise
        except Exception as error:
            if getattr(error,'sqlstate','') and error.sqlstate.startswith('08') or self.db.closed:raise BusinessError(503,'BUSINESS_DATABASE_UNAVAILABLE') from error
            raise
