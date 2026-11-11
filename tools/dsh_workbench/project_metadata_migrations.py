"""Explicit optional migration graph, independent of default 001--007 runner.

Only administrative connections; no role is created, inherited, or granted to a
runtime. 009 executor must already be a dedicated NOLOGIN non-owner role.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).with_name('migrations')
MANIFEST = ROOT / 'optional' / 'project_metadata_manifest.json'
MANIFEST_SHA256 = '2cab98addba23768cb852a4ead9c4a5ed7670c417ce39b1d9a7889b95f1b43bb'


def _plan(manifest):
    if type(manifest) is not dict or set(manifest) != {'schema', 'migrations'} or manifest['schema'] != 'wb.optional-migrations/v1':
        raise ValueError('MIGRATION_MANIFEST_INVALID')
    records = manifest['migrations']
    if type(records) is not list:
        raise ValueError('MIGRATION_MANIFEST_INVALID')
    nodes = {}
    for row in records:
        if type(row) is not dict or set(row) != {'version', 'dependencies', 'up', 'down', 'up_sha256', 'down_sha256'}:
            raise ValueError('MIGRATION_MANIFEST_INVALID')
        version = row['version']
        if type(version) is not int or version in nodes:
            raise ValueError('MIGRATION_DUPLICATE_OR_INVALID_VERSION')
        if type(row['dependencies']) is not list or any(type(d) is not int for d in row['dependencies']) or len(set(row['dependencies'])) != len(row['dependencies']):
            raise ValueError('MIGRATION_DEPENDENCY_INVALID')
        nodes[version] = row
    ordered, visiting, visited = [], set(), set()
    def visit(version):
        if version not in nodes:
            raise ValueError('MIGRATION_DEPENDENCY_MISSING')
        if version in visiting:
            raise ValueError('MIGRATION_DEPENDENCY_CYCLE')
        if version in visited:
            return
        visiting.add(version)
        for dependency in nodes[version]['dependencies']:
            visit(dependency)
        visiting.remove(version)
        visited.add(version)
        ordered.append(nodes[version])
    for version in sorted(nodes):
        visit(version)
    # This reviewed component authorizes exactly this graph, not future 008.
    if set(nodes) != {1, 2, 3, 4, 5, 6, 7, 9} or nodes[9]['dependencies'] != list(range(1, 8)):
        raise ValueError('MIGRATION_GRAPH_NOT_APPROVED')
    if any(nodes[v]['dependencies'] != ([] if v == 1 else [v-1]) for v in range(1, 8)):
        raise ValueError('MIGRATION_GRAPH_NOT_APPROVED')
    for row in ordered:
        for direction in ('up', 'down'):
            path = ROOT / row[direction]
            if path.resolve().parent not in (ROOT.resolve(), (ROOT / 'optional').resolve()):
                raise ValueError('MIGRATION_PATH_INVALID')
            if len(list(path.parent.glob('%03d_*.%s.sql' % (row['version'], direction)))) != 1:
                raise ValueError('MIGRATION_FILE_AMBIGUOUS')
            if hashlib.sha256(path.read_bytes()).hexdigest() != row[direction + '_sha256']:
                raise ValueError('MIGRATION_SOURCE_CHECKSUM_CONFLICT')
    return ordered


def _manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError('MIGRATION_MANIFEST_CHECKSUM_CONFLICT')
    return _plan(json.loads(raw.decode('utf-8')))


def _identifier(value):
    if type(value) is not str or not value or '\x00' in value:
        raise ValueError('MIGRATION_ROLE_INVALID')
    return '"' + value.replace('"', '""') + '"'


def _executor(connection, name):
    row = connection.execute('SELECT oid,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (name,)).fetchone()
    if not row or any(row[1:]):
        raise ValueError('METADATA_EXECUTOR_NOT_DEDICATED')
    if connection.execute('SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=%s OR roleid=%s)', (row[0], row[0])).fetchone()[0]:
        raise ValueError('METADATA_EXECUTOR_HAS_MEMBERSHIP')
    if connection.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wb' AND c.relowner=%s)", (row[0],)).fetchone()[0]:
        raise ValueError('METADATA_EXECUTOR_OWNS_TABLES')
    if connection.execute('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datdba=%s) OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=%s)', (row[0],row[0])).fetchone()[0]:
        raise ValueError('METADATA_EXECUTOR_OWNS_DATABASE_OR_SCHEMA')
    if connection.execute("SELECT has_parameter_privilege(%s,'session_replication_role','SET') OR has_parameter_privilege(%s,'session_replication_role','ALTER SYSTEM')", (name,name)).fetchone()[0]:
        raise ValueError('METADATA_EXECUTOR_DANGEROUS_PARAMETER_RIGHTS')
    return _identifier(name)


def migrate_project_metadata(connection, executor_role):
    """Explicit 009 after exact 001--007 applied; no implicit prefix application."""
    plan = _manifest()  # all files/graph validated before any SQL mutation
    if not connection.autocommit or connection.info.transaction_status != 0:
        raise ValueError('IDLE_AUTOCOMMIT_ADMIN_CONNECTION_REQUIRED')
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(684091210)')
        role = _executor(connection, executor_role)
        applied = dict(connection.execute('SELECT version,checksum FROM public.wb_schema_migration').fetchall())
        if set(applied) - {1, 2, 3, 4, 5, 6, 7, 9}:
            raise ValueError('MIGRATION_APPLIED_GRAPH_UNKNOWN')
        for row in plan:
            version = row['version']
            if version in applied and applied[version] != row['up_sha256']:
                raise ValueError('MIGRATION_CHECKSUM_CONFLICT')
            if version != 9 and version not in applied:
                raise ValueError('MIGRATION_DEPENDENCY_NOT_APPLIED')
        if 9 in applied:
            owner = connection.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='wb.rename_project_metadata(text,text,text,text,text,bytea,bytea)'::regprocedure").fetchone()[0]
            if owner != executor_role:
                raise ValueError('METADATA_EXECUTOR_CHANGED')
            return False
        if connection.execute("SELECT has_schema_privilege(%s,'wb','USAGE') OR has_schema_privilege(%s,'wb','CREATE')", (executor_role,executor_role)).fetchone()[0]:
            raise ValueError('METADATA_EXECUTOR_ALREADY_HAS_SCHEMA_PRIVILEGES')
        source = (ROOT / plan[-1]['up']).read_text(encoding='utf-8')
        connection.execute(source.replace('__M1_EXECUTOR__', role))
        connection.execute('INSERT INTO public.wb_schema_migration VALUES(9,%s)', (plan[-1]['up_sha256'],))
        return True


def grant_project_metadata_runtime(connection, runtime_role):
    """Administrative minimal EXECUTE grant; no table DML or role membership."""
    role = _identifier(runtime_role)
    if not connection.autocommit or connection.info.transaction_status != 0:
        raise ValueError('IDLE_AUTOCOMMIT_ADMIN_CONNECTION_REQUIRED')
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(684091210)')
        row=connection.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=%s",(runtime_role,)).fetchone()
        if not row or not row[0] or any(row[1:]):
            raise ValueError('METADATA_RUNTIME_ROLE_NOT_DEDICATED')
        connection.execute('GRANT EXECUTE ON FUNCTION wb.rename_project_metadata(text,text,text,text,text,bytea,bytea),wb.get_project_metadata(text) TO ' + role)


def downgrade_project_metadata(connection):
    plan = _manifest()
    if not connection.autocommit or connection.info.transaction_status != 0:
        raise ValueError('IDLE_AUTOCOMMIT_ADMIN_CONNECTION_REQUIRED')
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(684091210)')
        applied = dict(connection.execute('SELECT version,checksum FROM public.wb_schema_migration').fetchall())
        if set(applied) - {1, 2, 3, 4, 5, 6, 7, 9}:
            raise ValueError('MIGRATION_APPLIED_GRAPH_UNKNOWN')
        for row in plan:
            if row['version'] in applied and applied[row['version']] != row['up_sha256']:
                raise ValueError('MIGRATION_CHECKSUM_CONFLICT')
        if 9 not in applied:
            return False
        if not set(range(1,8)).issubset(applied):
            raise ValueError('MIGRATION_DEPENDENCY_NOT_APPLIED')
        executor = connection.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='wb.rename_project_metadata(text,text,text,text,text,bytea,bytea)'::regprocedure").fetchone()[0]
        source = (ROOT / plan[-1]['down']).read_text(encoding='utf-8')
        connection.execute(source.replace('__M1_EXECUTOR__', _identifier(executor)))
        connection.execute('DELETE FROM public.wb_schema_migration WHERE version=9')
        return True
