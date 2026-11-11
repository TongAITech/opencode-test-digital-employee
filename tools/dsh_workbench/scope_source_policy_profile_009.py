"""Explicit optional 009 catalog profile. Caller supplies trusted deployment roles."""
import json
from .scope_source_policy_profile import (
    TABLES, ReadOnlyScopeSourcePolicyQualification, _catalog, _definition, _hash, _rows,
)

PROFILE_ID_009 = 'dsh.scope-source.project-only.pg17.001-007-009.v1'
PROFILE_CONTENT_HASH_009 = 'f5e8629399b6b9f97f8480407b10495470e885b5518b60b99a8229dfc0f5a828'
_PROFILE_TABLES = TABLES + (
    'audit', 'request_log', 'project_namespace', 'project_name_binding',
    'project_namespace_population', 'project_metadata_result', 'project_metadata_history',
    'project_metadata_outbox', 'project_metadata_governance_fence',
)


def _sorted(rows):
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))


def _extension(connection, admin_role, executor_role):
    runtime = connection.execute('SELECT current_user::text').fetchone()[0]
    actors = {admin_role: 'ADMIN', executor_role: 'EXECUTOR', runtime: 'RUNTIME'}
    roles = _rows(connection, '''SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,
        rolcreatedb,rolcreaterole,rolreplication,
        has_parameter_privilege(oid,'session_replication_role','SET') AS parameter_set,
        has_parameter_privilege(oid,'session_replication_role','ALTER SYSTEM') AS parameter_alter_system,
        has_database_privilege(oid,current_database(),'CREATE') AS database_create,
        EXISTS(SELECT 1 FROM pg_namespace n WHERE has_schema_privilege(pg_roles.oid,n.oid,'CREATE')) AS schema_create
        FROM pg_roles WHERE rolname=ANY(%s)''', ([runtime, executor_role],))
    if len(actors) != 3 or len(roles) != 2:
        return {'role_identity': 'MISSING_OR_OVERLAPPING'}
    role_ids = {row['rolname']: row['oid'] for row in roles}
    for row in roles:
        row['role'] = actors[row.pop('rolname')]
        row.pop('oid')
    executor_oid = role_ids[executor_role]
    runtime_oid = role_ids[runtime]
    role_boundary = _rows(connection, '''SELECT
        (SELECT nspowner=to_regrole(quote_ident(%s)) FROM pg_namespace WHERE nspname='wb') AS approved_schema_owner,
        (SELECT count(*) FROM pg_auth_members WHERE roleid=%s OR member=%s) AS executor_membership_edges,
        (SELECT count(*) FROM pg_auth_members WHERE roleid=%s OR member=%s) AS runtime_membership_edges,
        (SELECT count(*) FROM pg_auth_members WHERE roleid=to_regrole(quote_ident(%s))) AS admin_incoming_membership_edges,
        EXISTS(SELECT 1 FROM pg_shdepend d WHERE d.refclassid='pg_authid'::regclass
          AND d.refobjid=%s AND d.deptype='o' AND NOT (d.dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
          AND d.classid='pg_proc'::regclass AND d.objid IN (SELECT p.oid FROM pg_proc p
            WHERE p.pronamespace=to_regnamespace('wb') AND p.proname IN ('get_project_metadata','rename_project_metadata')))) AS executor_other_ownership,
        pg_has_role(%s,%s,'SET') AS runtime_can_set_executor,
        current_setting('server_encoding') AS server_encoding''',
        (admin_role, executor_oid, executor_oid, runtime_oid, runtime_oid, admin_role, executor_oid, runtime_oid, executor_oid))[0]
    function_names = [row[0] for row in connection.execute('''SELECT DISTINCT proname::text
        FROM pg_proc WHERE pronamespace=to_regnamespace('wb') AND proname<>'allowed' ORDER BY 1''').fetchall()]
    extended = _catalog(connection, tables=_PROFILE_TABLES, support_functions=function_names, all_policies=True)
    definitions = _definition(extended)
    # Policy role identities must remain stable across disposable databases.
    policy_roles = {row[0]: actors.get(row[1], 'UNAPPROVED') for row in connection.execute('SELECT oid,rolname FROM pg_roles').fetchall()}
    policy_roles[0] = 'PUBLIC'
    for table in definitions['tables'].values():
        for policy in table['select_policies']:
            policy['polroles'] = sorted(policy_roles.get(oid, 'UNAPPROVED') for oid in policy['polroles'])
    ownership = _rows(connection, '''SELECT c.relname, c.relkind::text, pg_get_userbyid(c.relowner)::text AS owner
        FROM pg_class c WHERE c.relnamespace=to_regnamespace('wb') AND c.relkind IN('r','p','S','v','m','f')''')
    for row in ownership:
        row['owner'] = actors.get(row['owner'], 'UNAPPROVED')
    columns = _rows(connection, '''SELECT c.relname,a.attname,n.nspname AS collation_schema,co.collname,
        co.collprovider::text,co.collisdeterministic,co.collcollate,co.collctype,co.colllocale,co.collversion,
        has_column_privilege(%s,c.oid,a.attnum,'SELECT') AS executor_select,
        has_column_privilege(%s,c.oid,a.attnum,'INSERT') AS executor_insert,
        has_column_privilege(%s,c.oid,a.attnum,'UPDATE') AS executor_update,
        has_column_privilege(%s,c.oid,a.attnum,'REFERENCES') AS executor_references,
        has_column_privilege(%s,c.oid,a.attnum,'SELECT') AS runtime_select,
        has_column_privilege(%s,c.oid,a.attnum,'INSERT') AS runtime_insert,
        has_column_privilege(%s,c.oid,a.attnum,'UPDATE') AS runtime_update,
        has_column_privilege(%s,c.oid,a.attnum,'REFERENCES') AS runtime_references
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace n ON n.oid=co.collnamespace
        WHERE c.relnamespace=to_regnamespace('wb') AND c.relkind IN('r','p','v','m','f') AND a.attnum>0 AND NOT a.attisdropped''',
        (executor_oid,)*4 + (runtime_oid,)*4)
    # Direct ACLs include grantor, grantee and grant option, including PUBLIC.
    acl = _rows(connection, '''WITH objects AS (
        SELECT 'schema'::text AS kind,nspname::text AS object,nspowner AS owner,nspacl AS acl,'n'::"char" AS acl_kind
        FROM pg_namespace WHERE nspname='wb'
        UNION ALL SELECT 'relation',relname,relowner,relacl,CASE WHEN relkind='S' THEN 's'::"char" ELSE 'r'::"char" END
        FROM pg_class WHERE relnamespace=to_regnamespace('wb') AND relkind IN('r','p','S','v','m','f')
        UNION ALL SELECT 'routine',oid::regprocedure::text,proowner,proacl,'f'::"char" FROM pg_proc WHERE pronamespace=to_regnamespace('wb')
        UNION ALL SELECT 'column',c.relname||'.'||a.attname,c.relowner,a.attacl,'c'::"char" FROM pg_class c
        JOIN pg_attribute a ON a.attrelid=c.oid WHERE c.relnamespace=to_regnamespace('wb') AND a.attnum>0 AND a.attacl IS NOT NULL)
        SELECT kind,object,x.privilege_type,x.is_grantable,x.grantor,x.grantee FROM objects
        CROSS JOIN LATERAL aclexplode(COALESCE(acl,acldefault(acl_kind,owner))) x''')
    for row in acl:
        for key in ('grantor', 'grantee'):
            row[key] = policy_roles.get(row[key], 'UNAPPROVED')
    executor_routines = dict(connection.execute("""SELECT oid,has_function_privilege(%s,oid,'EXECUTE')
        FROM pg_proc WHERE pronamespace=to_regnamespace('wb')""", (executor_oid,)).fetchall())
    functions = []
    for row in extended['allowed_functions'] + extended['support_functions']:
        functions.append({'name': row['proname'], 'args': row['argument_types'],
                          'owner': actors.get(row['owner'], 'UNAPPROVED'),
                          'runtime_execute': row['can_execute'], 'executor_execute': executor_routines[row['oid']],
                          'public_execute': row['public_execute']})
    indexes = _rows(connection, '''SELECT t.relname AS relation,x.relname AS index,i.indisunique,i.indisprimary,
        i.indisvalid,i.indisready,i.indislive,i.indisreplident,pg_get_indexdef(i.indexrelid) AS definition
        FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_class x ON x.oid=i.indexrelid
        WHERE t.relnamespace=to_regnamespace('wb') AND t.relname=ANY(%s)''', (list(_PROFILE_TABLES),))
    inheritance = _rows(connection, '''SELECT i.inhrelid::regclass::text AS child,i.inhparent::regclass::text AS parent,
        i.inhdetachpending FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid OR c.oid=i.inhparent
        WHERE c.relnamespace=to_regnamespace('wb') AND c.relname=ANY(%s)''', (list(_PROFILE_TABLES),))
    # Expose only stable digests outside this observer. Definitions of unapproved
    # functions, indexes or policies can contain arbitrary text literals.
    return {'role_boundary': role_boundary, 'roles': _sorted(roles), 'definitions': definitions,
            'ownership': _sorted(ownership), 'column_boundary': _sorted(columns),
            'acl': _sorted(acl), 'function_boundary': _sorted(functions),
            'indexes': _sorted(indexes), 'inheritance': _sorted(inheritance)}


class ReadOnlyScopeSourcePolicyQualification009(ReadOnlyScopeSourcePolicyQualification):
    """Explicit catalog observation for 009, with trusted role identity inputs."""
    _profile_id = PROFILE_ID_009
    _profile_filename = 'scope_source_profile_009_pg17.json'
    _profile_content_hash = PROFILE_CONTENT_HASH_009

    def __init__(self, connection, *, admin_role, executor_role, statement_timeout_ms=5000):
        if (type(admin_role) is not str or type(executor_role) is not str or not admin_role or not executor_role
                or '\x00' in admin_role or '\x00' in executor_role or admin_role == executor_role):
            raise ValueError('APPROVED_009_ROLE_IDENTITIES_REQUIRED')
        self._admin_role, self._executor_role = admin_role, executor_role
        super().__init__(connection, statement_timeout_ms=statement_timeout_ms)

    def _observe(self):
        facts = super()._observe()
        sections = _extension(self.db, self._admin_role, self._executor_role)
        facts['profile_009_sections'] = {name: _hash(value) for name, value in sections.items()}
        return facts

    def _validate_extension(self, facts, reject):
        actual = facts['profile_009_sections']
        expected = self._profile['section_hashes']
        for name in sorted(set(actual) | set(expected)):
            if actual.get(name) != expected.get(name):
                reject('OPTIONAL_009_CATALOG_PROFILE_DRIFT', name)
