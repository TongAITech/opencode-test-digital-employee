"""Internal PostgreSQL candidate; trusted caller must prove Host mutation/context.

No HTTP, namespace governance mutation, DTO authority or R1 interaction. Existing
BusinessStore IDLE scoped transaction protection is composed, never weakened.
"""
from .business_store import BusinessError, BusinessStore
from .project_metadata_codec import MetadataRenameRequest


class ProjectMetadataStore:
    def __init__(self, connection):
        self.db = connection
        self._transactions = BusinessStore(connection)

    @staticmethod
    def _error(error):
        if isinstance(error, BusinessError) and error.code == 'BUSINESS_DATABASE_UNAVAILABLE':
            return BusinessError(503, 'METADATA_DATABASE_UNAVAILABLE')
        state = getattr(error, 'sqlstate', None)
        message = getattr(getattr(error, 'diag', None), 'message_primary', '')
        allowed = {'FORBIDDEN', 'METADATA_NOT_GOVERNED', 'GOVERNANCE_HOLD',
                   'REVISION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'NAME_UNAVAILABLE',
                   'REVISION_EXHAUSTED', 'INVALID_METADATA_REQUEST', 'INVALID_METADATA_CANONICAL',
                   'METADATA_RETRY_REQUIRED'}
        if state == 'P0001' and message in allowed:
            status = 403 if message == 'FORBIDDEN' else 400 if message.startswith('INVALID_') else 503 if message == 'METADATA_RETRY_REQUIRED' else 409
            return BusinessError(status, message)
        if state in ('55P03', '57014', '40P01', '40001'):
            return BusinessError(503, 'METADATA_RETRY_REQUIRED')
        return None

    def _bound_wait(self):
        # Bound the business operation without weakening a stricter caller cap.
        # Preexisting scope/auth connection checkout and DDL availability remain
        # the responsibility of the deployment connection/deadline policy.
        self.db.execute("""SELECT set_config(name, CASE WHEN setting::integer=0 OR setting::integer>limits.ms
                           THEN limits.ms::text||'ms' ELSE current_setting(name) END,true)
                           FROM pg_catalog.pg_settings JOIN
                           (VALUES ('lock_timeout',1500),('statement_timeout',5000)) limits(name,ms) USING(name)""")

    def get_metadata(self, principal, project_id):
        try:
            with self._transactions._scope(principal, project_id, False, isolation='repeatable read'):
                self._bound_wait()
                return self.db.execute('SELECT wb.get_project_metadata(%s)', (project_id,)).fetchone()[0]
        except Exception as error:
            mapped = self._error(error)
            if mapped:
                raise mapped from error
            raise

    def rename(self, principal, request):
        if type(request) is not MetadataRenameRequest:
            raise ValueError('METADATA_SYNTAX_REQUEST_REQUIRED')
        try:
            with self._transactions._scope(principal, request.project_id):
                self._bound_wait()
                return self.db.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s,%s,%s)',
                    (request.project_id, request.request_id, request.expected_metadata_revision,
                     request.expected_access_scope_revision, request.name,
                     request.reason.encode('utf-8'), request.canonical_bytes)).fetchone()[0]
        except Exception as error:
            mapped = self._error(error)
            if mapped:
                raise mapped from error
            raise
