"""Read-only B06/R1 component. No runtime command or R1 mutation API."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, unquote
from rc6_runtime.truth import TruthRuntime
from rc7_admin.projection import AdminProjection, AdminProjectionError
from .business_store import BusinessError
from .e_b06_page_consumer import collect_authorized_b06_pages
from .e_readonly_scope_prototype import r1_preview
from .e_contract_oracle import ContractRejection


class E01Service:
    def __init__(self, scope_store, r1_path, evidence_root, max_r1_bytes=64*1024*1024):
        self.scope_store=scope_store
        self.r1_path=Path(r1_path)
        self.evidence_root=Path(evidence_root).resolve()
        self.max_r1_bytes=max_r1_bytes

    def _evidence(self, row):
        value={'id':row['evidence_id'],'integrity':'UNVERIFIED','content_hash':row.get('content_hash')}
        try:
            uri=urlsplit(row.get('content_ref',''))
            if uri.scheme!='file' or uri.netloc or uri.query or uri.fragment:raise ValueError()
            path=Path(unquote(uri.path)).resolve(strict=True)
            path.relative_to(self.evidence_root)
            if not path.is_file():raise ValueError()
            if path.stat().st_size>64*1024*1024:raise ValueError()
            declared=row.get('content_hash','')
            actual='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
            value['integrity']='HASH_VERIFIED_ONLY' if declared==actual else 'HASH_MISMATCH'
        except Exception:
            value['integrity']='CONTENT_UNAVAILABLE'
        return value

    def quality(self, principal, project, batch, release_date, mission_id, page_size=100):
        # Every page is authorized by the real PostgreSQL store; no caller DTO
        # or body-supplied principal can replace the server-bound identity.
        try:
            def fetch(p,b,size,cursor):
                page=self.scope_store.scope(principal,p,b,release_date=release_date,page_size=size,page_cursor=cursor)
                # Real B06 rows inherit their project/batch from the authorized
                # envelope; expand only for the legacy DTO checker.
                page['records']=[dict(row,project_id=page['project_id'],batch_id=page['batch_id']) for row in page['records']]
                return page
            scope=collect_authorized_b06_pages(
                fetch,
                project_id=project,batch_id=batch,page_size=page_size)
            # Bound immutable byte snapshot; reads never instantiate TruthRuntime
            # on the original path (its constructor touches/creates the file).
            with self.r1_path.open('rb') as source:
                data=source.read(self.max_r1_bytes+1)
            if len(data)>self.max_r1_bytes:raise ValueError('R1_SNAPSHOT_TOO_LARGE')
            revision='sha256:'+hashlib.sha256(data).hexdigest()
            with TemporaryDirectory(prefix='wb-e01-read-') as temporary:
                snapshot=Path(temporary)/'r1.jsonl';snapshot.write_bytes(data)
                runtime=TruthRuntime(snapshot)
                overview=AdminProjection(runtime).mission_overview_scoped(mission_id=mission_id,project_id=project,batch_id=batch)
                value=r1_preview(scope,overview,project_id=project,batch_id=batch,mission_id=mission_id)
            def recheck_scope():
                check = self.scope_store.scope(principal, project, batch, release_date=release_date,
                                               page_size=page_size)
                if any(check[k] != scope[k] for k in ('relation_revision', 'access_scope_revision', 'release_date')):
                    raise BusinessError(409, 'SCOPE_CHANGED_DURING_READ')

            # Reauthorize before opening evidence and again after the file reads.
            recheck_scope()
            evidence = [self._evidence(row) for row in overview['related']['evidence']]
            if evidence:
                recheck_scope()
            value.update(truth_revision=revision, as_of=datetime.now(timezone.utc).isoformat(),
                         data_quality='READ_ONLY_SNAPSHOT', evidence=evidence)
            value['gap_indicators']=[g for g in scope['gap_indicators']]+['CANONICAL_NODEGATE_NOT_PROJECTED','ATTEMPT_LINEAGE_NOT_QUALIFIED']
            if any(e['integrity']!='HASH_VERIFIED_ONLY' for e in value['evidence']):value['gap_indicators'].append('EVIDENCE_INTEGRITY_UNRESOLVED')
            if not value['evidence']:value['gap_indicators'].append('EVIDENCE_MISSING')
            # A matching content hash is never evidence provenance or a Gate PASS.
            value['release_decision']='HOLD'
            return value
        except BusinessError:raise
        except AdminProjectionError as error:
            if str(error)=='R1_MISSION_SCOPE_UNRESOLVED':raise BusinessError(403,'FORBIDDEN') from error
            raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE') from error
        except ContractRejection as error:
            raise BusinessError(503,'SCOPE_CONTRACT_INVALID') from error
        except Exception as error:
            raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE') from error
