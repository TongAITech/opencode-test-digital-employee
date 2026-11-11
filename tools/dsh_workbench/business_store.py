"""B01/B02 PostgreSQL repository. Caller supplies a server-authenticated identity.

Use a dedicated non-owner runtime connection; never expose this interface directly
as an HTTP body/query principal. No R1 writes or runtime facts exist here.
"""
import hashlib
import datetime
import json
from contextlib import contextmanager


class BusinessError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


class BusinessStore:
    def __init__(self, connection):
        if not connection.autocommit:
            raise ValueError("AUTOCOMMIT_CONNECTION_REQUIRED_FOR_SCOPED_TRANSACTIONS")
        self.db = connection

    @contextmanager
    def _scope(self, principal, project, write=True, isolation=None):
        if self.db.closed:
            raise BusinessError(503,'BUSINESS_DATABASE_UNAVAILABLE')
        if self.db.info.transaction_status != 0:
            raise ValueError('IDLE_CONNECTION_REQUIRED_FOR_SCOPED_TRANSACTIONS')
        if not principal or not project:
            raise BusinessError(403, 'FORBIDDEN')
        try:
            with self.db.transaction():
                if isolation == 'repeatable read':
                    self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                elif isolation is not None:
                    raise ValueError('INVALID_TRANSACTION_ISOLATION')
                self.db.execute("SELECT set_config('wb.principal',%s,true)", (principal,))
                allowed = self.db.execute('SELECT wb.allowed(%s,%s)', (project,write)).fetchone()[0]
                if not allowed:
                    raise BusinessError(403, 'FORBIDDEN')
                yield
        except Exception as error:
            code = getattr(error, 'sqlstate', None)
            if (code and code.startswith('08')) or type(error).__name__ in ('OperationalError','InterfaceError'):
                raise BusinessError(503, 'BUSINESS_DATABASE_UNAVAILABLE') from error
            if code == '23505':
                raise BusinessError(409, 'IDENTITY_OR_DATE_CONFLICT') from error
            if code in ('23503','23514','23502','22007','22008'):
                raise BusinessError(422, 'ILLEGAL_IDENTITY') from error
            raise

    def _claim(self, project, principal, request, payload):
        if not request or not request.strip():
            raise BusinessError(400,'REQUEST_ID_REQUIRED')
        digest = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        inserted = self.db.execute('INSERT INTO wb.request_log VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING request_id',(project,principal,request,digest)).fetchone()
        if inserted:
            return False
        previous = self.db.execute('SELECT payload_hash FROM wb.request_log WHERE project_id=%s AND actor=%s AND request_id=%s',(project,principal,request)).fetchone()
        if not previous or previous[0] != digest:
            raise BusinessError(409,'IDEMPOTENCY_PAYLOAD_CONFLICT')
        return True

    def _audit(self, project, principal, request, action, object_id, detail):
        if not request or not request.strip():
            raise BusinessError(400, 'REQUEST_ID_REQUIRED')
        return self.db.execute('INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail) VALUES(%s,%s,%s,%s,%s,%s::jsonb) RETURNING audit_id', (project,principal,request,action,object_id,json.dumps(detail))).fetchone()[0]

    def create_batch(self, principal, project, batch, date, request):
        date = self._date(date)
        with self._scope(principal,project):
            if self._claim(project,principal,request,['batch',batch,str(date)]):
                return
            self.db.execute('INSERT INTO wb.release_batch(project_id,batch_id,release_date) VALUES(%s,%s,%s)', (project,batch,date))
            self._audit(project,principal,request,'batch.create',batch,{'date':str(date),'revision':1})

    @staticmethod
    def _date(value):
        try:
            if not isinstance(value,str) or len(value)!=10:
                raise ValueError()
            return datetime.date.fromisoformat(value)
        except (ValueError,TypeError):
            raise BusinessError(400,'INVALID_BUSINESS_DATE')

    def reschedule(self, principal, project, batch, date, expected, request, reason, approval):
        date = self._date(date)
        if not reason or not reason.strip() or not approval or not approval.strip():
            raise BusinessError(400,'DATE_CHANGE_AUDIT_REQUIRED')
        with self._scope(principal,project):
            if self._claim(project,principal,request,['reschedule',batch,str(date),expected,reason,approval]):
                return expected+1
            row = self.db.execute('SELECT release_date,revision FROM wb.release_batch WHERE project_id=%s AND batch_id=%s FOR UPDATE', (project,batch)).fetchone()
            if row is None:
                raise BusinessError(404,'RESOURCE_NOT_FOUND')
            old, revision = row
            if revision != expected:
                raise BusinessError(409,'STATE_REVISION_CONFLICT')
            if old == date:
                raise BusinessError(422,'DATE_UNCHANGED')
            self.db.execute('UPDATE wb.release_batch SET release_date=%s,revision=revision+1 WHERE project_id=%s AND batch_id=%s', (date,project,batch))
            audit = self._audit(project,principal,request,'batch.reschedule',batch,{'old':str(old),'new':str(date),'revision':revision+1})
            self.db.execute('INSERT INTO wb.batch_date_history VALUES(%s,%s,%s,%s,%s,%s,%s,%s)', (project,batch,revision+1,old,date,reason,approval,audit))
            return revision+1

    def create_system(self, principal, project, system, source, namespace, object_id, source_revision, request):
        with self._scope(principal,project):
            if self._claim(project,principal,request,['system',system,source,namespace,object_id,source_revision]):
                return
            self.db.execute('INSERT INTO wb.system_identity VALUES(%s,%s,%s,%s,%s,%s)', (project,system,source,namespace,object_id,source_revision))
            self._audit(project,principal,request,'system.create',system,{'source_revision':source_revision})

    def create_version(self, principal, project, version, system, label, source, namespace, object_id, source_revision, request):
        with self._scope(principal,project):
            if self._claim(project,principal,request,['version',version,system,label,source,namespace,object_id,source_revision]):
                return
            self.db.execute('INSERT INTO wb.system_version VALUES(%s,%s,%s,%s,%s,%s,%s,%s)', (project,version,system,label,source,namespace,object_id,source_revision))
            self._audit(project,principal,request,'version.create',version,{'source_revision':source_revision})

    def batches(self, principal, project):
        with self._scope(principal,project,False):
            return self.db.execute('SELECT batch_id,release_date,revision FROM wb.release_batch WHERE project_id=%s ORDER BY release_date,batch_id', (project,)).fetchall()


def provision_project(owner_connection, project, name, principal, request):
    """Administrative bootstrap only; use an owner connection outside HTTP flows."""
    with owner_connection.transaction():
        owner_connection.execute('INSERT INTO wb.project VALUES(%s,%s)',(project,name))
        owner_connection.execute('INSERT INTO wb.project_acl VALUES(%s,%s,true)',(project,principal))
        owner_connection.execute("INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail) VALUES(%s,%s,%s,'project.provision',%s,'{}')",(project,principal,request,project))
