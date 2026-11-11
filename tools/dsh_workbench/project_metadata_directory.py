"""Explicit optional 009 directory projection; old wire and batch path unchanged.

Not selected by current HTTP. Internal all-authorized-row snapshot version and
metadata revisions prevent project-name ABA, without touching Scope numeric
revisions or exposing metadata fields in legacy directory records.
"""
from .business_directory import DirectoryStore


class MetadataDirectoryStore(DirectoryStore):
    def _project_directory_snapshot(self):
        rows = self.db.execute('SELECT project_id,name,access_scope_revision,metadata_revision FROM wb.project ORDER BY project_id').fetchall()
        records = [dict(zip(['project_id', 'name', 'access_scope_revision'], row[:3])) for row in rows]
        snapshot = {'projection': 'project-directory/metadata-revision/v1',
                    'records': records,
                    'metadata_revisions': [[row[0], str(row[3])] for row in rows]}
        return records, snapshot
