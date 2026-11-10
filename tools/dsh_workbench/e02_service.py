"""Canonical RC72 graph read model; never dispatches or writes runtime facts."""
from tempfile import TemporaryDirectory
from pathlib import Path
import hashlib
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.rc72_domain import RC72_CANONICAL_NODE_ORDER
from rc7_admin.projection import AdminProjection
from .business_store import BusinessError
from .e01_service import E01Service
from .e02_lineage import validate_lineage

install_rc72_truth_overlay()

class E02Service(E01Service):
    def graph(self,principal,project,batch,release_date,mission_id,view='graph'):
        # E01 performs full B06 authorization, canonical identity and post-read ACL.
        base=self.quality(principal,project,batch,release_date,mission_id)
        try:
            with self.r1_path.open('rb') as source:data=source.read(self.max_r1_bytes+1)
            if len(data)>self.max_r1_bytes or 'sha256:'+hashlib.sha256(data).hexdigest()!=base['truth_revision']:
                raise BusinessError(409,'TRUTH_CHANGED_DURING_READ')
            with TemporaryDirectory(prefix='wb-e02-') as tmp:
                path=Path(tmp)/'r1';path.write_bytes(data);truth=TruthRuntime(path)
                # Identity-only admission again before any graph detail query.
                missions=truth.query('rc7_mission',mission_id=mission_id)
                if len(missions)!=1 or missions[0].get('project_id')!=project or missions[0].get('batch_id')!=batch:
                    raise BusinessError(403,'FORBIDDEN')
                kinds=('rc72_mission_node','rc72_node_delivery','rc72_node_gate','rc72_node_transition','rc72_back_edge') if view=='graph' else ('rc7_task','rc72_etu','rc72_workitem_attempt_binding')
                all_kinds=('rc72_mission_node','rc72_node_delivery','rc72_node_gate','rc72_node_transition','rc72_back_edge','rc7_task','rc72_etu','rc72_workitem_attempt_binding','execution_attempt','rc72_test_obligation')
                all_records={kind:truth.query(kind,mission_id=mission_id) for kind in all_kinds}
                validate_lineage(all_records,missions[0],batch)
                records={kind:all_records[kind] for kind in kinds}
                # All canonical records must belong to this exact Mission release.
                if any(row.get('release_id')!=missions[0].get('release_id') for rows in records.values() for row in rows):
                    raise BusinessError(503,'R1_LINEAGE_UNRESOLVED')
            check=self.scope_store.scope(principal,project,batch,release_date=release_date)
            if any(check[k]!=base[k] for k in ('relation_revision','access_scope_revision')):raise BusinessError(409,'SCOPE_CHANGED_DURING_READ')
            result={k:base[k] for k in ('project_id','batch_id','mission_id','release_date','relation_revision','access_scope_revision','truth_revision','as_of','source_refs')}
            result.update(records=records,release_decision='HOLD',human_approval='UNKNOWN_NOT_QUERIED',gap_indicators=[])
            if view=='graph':
                present={row['node_type'] for row in records['rc72_mission_node']}
                result['missing_nodes']=[node for node in RC72_CANONICAL_NODE_ORDER if node not in present]
                if result['missing_nodes']:result['gap_indicators'].append('CANONICAL_NODES_MISSING')
                if not records['rc72_node_gate']:result['gap_indicators'].append('CANONICAL_NODEGATES_MISSING')
            # Report canonical states/decisions as recorded, never infer PASS from
            # node state, draft records, overlay labels, or absent human approval.
            return result
        except BusinessError:raise
        except Exception as error:raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE') from error
