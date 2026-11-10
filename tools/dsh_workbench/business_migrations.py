"""Transactional migration runner for a dedicated PostgreSQL migration owner."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).with_name('migrations')


def migrate(connection, target=1):
    """Apply the explicitly selected reviewed migration prefix atomically."""
    if target not in (1,2,3,4,5,6,7):
        raise ValueError('UNKNOWN_MIGRATION_TARGET')
    changed=False
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(684091210)")
        connection.execute('CREATE TABLE IF NOT EXISTS public.wb_schema_migration(version integer PRIMARY KEY, checksum text NOT NULL)')
        for version in range(1,target+1):
            files=list(ROOT.glob('%03d_*.up.sql' % version))
            if len(files)!=1:
                raise RuntimeError('MIGRATION_FILE_AMBIGUOUS')
            content=files[0].read_text()
            digest=hashlib.sha256(content.encode()).hexdigest()
            row=connection.execute('SELECT checksum FROM public.wb_schema_migration WHERE version=%s',(version,)).fetchone()
            if row:
                if row[0]!=digest:
                    raise RuntimeError('MIGRATION_CHECKSUM_CONFLICT')
                continue
            connection.execute(content)
            connection.execute('INSERT INTO public.wb_schema_migration VALUES(%s,%s)',(version,digest))
            changed=True
    return changed


def rollback(connection):
    """Only empty schemas roll back automatically. Accepted writes require restore plan."""
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(684091210)')
        for table in ['project','release_batch','system_identity','system_version','audit','batch_date_history','request_log']:
            if connection.execute('SELECT EXISTS(SELECT 1 FROM wb.'+table+')').fetchone()[0]:
                raise RuntimeError('ROLLBACK_REQUIRES_BACKUP_AND_RECONCILIATION')
        connection.execute((ROOT/'001_identity.down.sql').read_text())
        connection.execute('DELETE FROM public.wb_schema_migration WHERE version=1')


def downgrade(connection, target):
    """Empty incremental relation tables only; accepted records require restore plan."""
    tables={7:['asset_payload'],6:['asset_root','asset_revision','asset_brv_link','asset_brvs_link','asset_outbox','asset_request_result'],4:['batch_requirement_version_sst','verified_sst_link','sst_identity'],3:['batch_requirement_version','verified_requirement_version'],2:['batch_requirement','batch_version','requirement']}
    if target not in (1,2,3,5,6): raise ValueError('UNKNOWN_MIGRATION_TARGET')
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(684091210)')
        versions=connection.execute('SELECT version FROM public.wb_schema_migration WHERE version>%s ORDER BY version DESC',(target,)).fetchall()
        for (version,) in versions:
            if version==5:
                raise RuntimeError('ROLLBACK_REQUIRES_BACKUP_AND_RECONCILIATION_SCOPE_CURSOR_KEY_ROTATION')
            for table in tables[version]:
                if connection.execute('SELECT EXISTS(SELECT 1 FROM wb.'+table+')').fetchone()[0]:
                    raise RuntimeError('ROLLBACK_REQUIRES_BACKUP_AND_RECONCILIATION')
            files=list(ROOT.glob('%03d_*.down.sql' % version))
            if len(files)!=1: raise RuntimeError('MIGRATION_FILE_AMBIGUOUS')
            connection.execute(files[0].read_text())
            connection.execute('DELETE FROM public.wb_schema_migration WHERE version=%s',(version,))
