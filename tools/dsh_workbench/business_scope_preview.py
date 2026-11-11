"""Internal read-only V3 source preview. Not a create/admission/verifier port.

The caller must bind principal from its trusted server identity. This adapter
owns an IDLE connection transaction, uses existing project ACL/RLS and never
opens R1, allocates identities, changes a business row or grants creation rights.
Returned data is an as-of REPEATABLE READ preview, not a current submit permit.
"""
import json

from .business_store import BusinessStore, BusinessError


_FROM = ''' FROM wb.batch_requirement_version r
 LEFT JOIN wb.verified_requirement_version rv USING(project_id,batch_id,requirement_id,version_id)
 LEFT JOIN wb.batch_requirement member_r USING(project_id,batch_id,requirement_id)
 LEFT JOIN wb.batch_version member_v USING(project_id,batch_id,version_id)
 LEFT JOIN wb.requirement q ON q.project_id=r.project_id AND q.requirement_id=r.requirement_id
 LEFT JOIN wb.system_version v ON v.project_id=r.project_id AND v.version_id=r.version_id
 LEFT JOIN wb.system_identity sy ON sy.project_id=v.project_id AND sy.system_id=v.system_id
 LEFT JOIN wb.batch_requirement_version_sst s ON s.project_id=r.project_id AND s.batch_id=r.batch_id AND s.requirement_id=r.requirement_id AND s.version_id=r.version_id
 LEFT JOIN wb.verified_sst_link l ON l.project_id=r.project_id AND l.batch_id=r.batch_id AND l.requirement_id=r.requirement_id AND l.version_id=r.version_id AND l.sst_id=s.sst_id
 LEFT JOIN wb.sst_identity si ON si.project_id=r.project_id AND si.version_id=r.version_id AND si.sst_id=s.sst_id
 WHERE r.project_id=%s AND r.batch_id=%s'''

_SOURCE_COLUMNS = [
    'r.requirement_id', 'v.system_id', 'r.version_id', 's.sst_id',
    'q.source_system', 'q.source_namespace', 'q.source_object_id', 'q.source_revision', 'q.source_ref',
    'v.source_system', 'v.source_namespace', 'v.source_object_id', 'v.source_revision',
    'rv.source_link_ref', 'rv.source_revision',
    'si.source_system', 'si.source_namespace', 'si.source_object_id', 'si.source_revision', 'si.source_ref',
    'l.source_link_ref', 'l.verified_source_revision',
]
_RAW_SIZE = '+'.join('COALESCE(octet_length(%s),0)' % name for name in _SOURCE_COLUMNS)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise BusinessError(400, 'INVALID_SCOPE_PREVIEW_REQUEST')
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError as error:
        raise BusinessError(400, 'INVALID_SCOPE_PREVIEW_REQUEST') from error
    return value


def _ids(values):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise BusinessError(400, 'INVALID_SCOPE_PREVIEW_REQUEST')
    result = [_text(value) for value in values]
    if any(len(value) > 256 for value in result) or len(set(result)) != len(result):
        raise BusinessError(400, 'INVALID_SCOPE_PREVIEW_REQUEST')
    return sorted(result, key=lambda value: value.encode('utf-8'))


def _source(kind, names, values):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise BusinessError(503, 'SCOPE_PREVIEW_SOURCE_UNAVAILABLE')
    return dict(kind=kind, **dict(zip(names, values)))


class ReadOnlyScopeSnapshotPreview:
    """Only a complete bounded read model; never an admission certificate."""

    def __init__(self, connection, *, max_edges=10000, max_bytes=4*1024*1024, statement_timeout_ms=5000):
        self._store = BusinessStore(connection)
        self.db = connection
        for name, value, maximum in (
            ('max_edges', max_edges, 100000), ('max_bytes', max_bytes, 64*1024*1024),
            ('statement_timeout_ms', statement_timeout_ms, 30000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('INVALID_SCOPE_PREVIEW_BUDGET_' + name.upper())
        self.max_edges, self.max_bytes, self.statement_timeout_ms = max_edges, max_bytes, statement_timeout_ms

    def preview(self, principal, project, batch, *, release_date=None, requirement_ids=None, version_ids=None, sst_ids=None):
        for value in (principal, project, batch):
            if len(_text(value)) > 256:
                raise BusinessError(400, 'INVALID_SCOPE_PREVIEW_REQUEST')
        expected_date = str(self._store._date(release_date)) if release_date is not None else None
        filters = [_ids(values) for values in (requirement_ids, version_ids, sst_ids)]
        try:
            with self._store._scope(principal, project, False, isolation='repeatable read'):
                self.db.execute("SELECT set_config('statement_timeout',%s,true)", (str(self.statement_timeout_ms),))
                header = self.db.execute('''SELECT b.release_date,b.revision,b.relation_revision,p.access_scope_revision
                    FROM wb.release_batch b JOIN wb.project p USING(project_id)
                    WHERE b.project_id=%s AND b.batch_id=%s''', (project, batch)).fetchone()
                if header is None:
                    raise BusinessError(404, 'RESOURCE_NOT_FOUND')
                actual_date, date_revision, relation_revision, access_revision = header
                if expected_date is not None and expected_date != str(actual_date):
                    raise BusinessError(409, 'SCOPE_PREVIEW_DATE_CHANGED')
                query, parameters = _FROM, [project, batch]
                for values, column in zip(filters, ['r.requirement_id', 'r.version_id', 's.sst_id']):
                    if values:
                        query += ' AND ' + column + '=ANY(%s)'
                        parameters.append(values)
                counts = self.db.execute('SELECT count(*),count(DISTINCT r.requirement_id),count(DISTINCT r.version_id),count(DISTINCT s.sst_id),COALESCE(sum(' + _RAW_SIZE + '),0)' + query, parameters).fetchone()
                if not counts[0] or any(values and len(values) != count for values, count in zip(filters, counts[1:4])):
                    raise BusinessError(422, 'ILLEGAL_ASSOCIATION')
                if counts[0] > self.max_edges or counts[4] > self.max_bytes:
                    raise BusinessError(413, 'SCOPE_PREVIEW_BUDGET_EXCEEDED')
                rows = self.db.execute('SELECT ' + ','.join(_SOURCE_COLUMNS) + ',member_r.requirement_id,member_v.version_id,sy.system_id' + query +
                    ' ORDER BY r.requirement_id COLLATE "C",v.system_id COLLATE "C",r.version_id COLLATE "C",s.sst_id COLLATE "C" NULLS FIRST LIMIT %s', parameters + [self.max_edges + 1]).fetchall()
                if len(rows) != counts[0] or len(rows) > self.max_edges:
                    raise BusinessError(503, 'SCOPE_PREVIEW_INCOMPLETE')
                edges = []
                for row in rows:
                    requirement, system, version, sst = row[:4]
                    if row[22:] != (requirement, version, system) or not system:
                        raise BusinessError(503, 'SCOPE_PREVIEW_SOURCE_UNAVAILABLE')
                    identity_fields = ['source_system', 'source_namespace', 'source_object_id', 'source_revision']
                    edge = {
                        'requirement_id': requirement, 'system_id': system, 'version_id': version, 'sst_id': sst,
                        'requirement_source': _source('REQUIREMENT_IDENTITY', identity_fields + ['source_ref'], row[4:9]),
                        'version_source': _source('SYSTEM_VERSION_IDENTITY', identity_fields, row[9:13]),
                        'brv_source': _source('VERIFIED_REQUIREMENT_VERSION', ['source_link_ref', 'source_revision'], row[13:15]),
                        'sst_source': None if sst is None else _source('SST_IDENTITY', identity_fields + ['source_ref'], row[15:20]),
                        'brvs_source': None if sst is None else _source('VERIFIED_SST_LINK', ['source_link_ref', 'verified_source_revision'], row[20:22]),
                    }
                    edges.append(edge)
                # Native PostgreSQL bigint/date are read in the same snapshot as every edge.
                snapshot = {
                    'schema_version': 1, 'project_id': project, 'batch_id': batch, 'release_date': str(actual_date),
                    'date_revision': date_revision, 'relation_revision': relation_revision, 'access_scope_revision': access_revision,
                    'filters': dict(zip(['requirement_ids', 'version_ids', 'sst_ids'], filters)), 'edges': edges,
                }
                # This is a byte budget check, not a canonical encoding/digest or an admission decision.
                if len(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > self.max_bytes:
                    raise BusinessError(413, 'SCOPE_PREVIEW_BUDGET_EXCEEDED')
                return {'preview_state': 'READ_ONLY_SNAPSHOT_NOT_ADMISSION', 'snapshot': snapshot}
        except Exception as error:
            if getattr(error, 'sqlstate', None) in ('42501', '42P01', '42703'):
                raise BusinessError(503, 'SCOPE_PREVIEW_SOURCE_UNAVAILABLE') from error
            if getattr(error, 'sqlstate', None) == '57014':
                raise BusinessError(503, 'SCOPE_PREVIEW_READ_TIMEOUT') from error
            raise
