"""Signed, complete evidence of an observed frozen-contract discrepancy.

This is input for independent diagnosis, never a product-defect or Case PASS
verdict. All ordinary positive N7 review predicates remain unchanged.
"""
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path

from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n7_evidence_review import ExecutionEvidenceReviewService
from .rc72_n7_execution_admission import _hash

KIND = 'N7_CONCLUSIVE_ASSERTION_FAILURE'


class ConclusiveAssertionFailureEvidence:
    def __init__(self, review):
        if not isinstance(review, ExecutionEvidenceReviewService):
            raise ContractError('CONCLUSIVE_FAILURE_NATIVE_REVIEW_REQUIRED')
        self.review, self.preparation, self.truth = review, review.preparation, review.truth

    def _context(self, preparation_id):
        p,c,b,a,dispatch,oracle = self.review.evidence.observation(preparation_id)
        attempt = self.preparation._one('execution_attempt', attempt_id=p['attempt_id'])
        if (p.get('status') != 'PREPARED' or b.get('state') != 'EVIDENCE_READY'
                or dispatch['state'] != 'RETURNED' or not oracle or oracle['passed'] is not False
                or attempt['status'] != 'BLOCKED' or attempt['reason'] != 'ORACLE_FAILED'):
            raise ContractError('CONCLUSIVE_FAILURE_ACTUAL_ASSERTION_DISCREPANCY_REQUIRED')
        plan = self.preparation._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
        items = [r for r in plan['items'] if r['workitem_id'] == p['workitem_id'] and r['case_id'] == p['case_id']]
        design = CanonicalDesignService(self.truth,release_id=p['release_id'],source_commit=p['source_commit']).load(
            release_batch_id=p['release_batch_id'])
        cases = {r['tc_id']:r for r in design.cases}
        if len(items) != 1 or {r['case_id'] for r in plan['items']} != set(cases):
            raise ContractError('CONCLUSIVE_FAILURE_FULL_PLAN_SCOPE_REQUIRED')
        snapshot = self.review._case_snapshot(plan,items[0],cases,p,allow_business_failure=True)
        if snapshot['formal_proof_gaps']:
            raise ContractError('CONCLUSIVE_FAILURE_FORMAL_RUNNER_REQUIRED')
        # Older unsigned cleanup history cannot be upgraded to a conclusive
        # business failure merely because its mutable status says RETURNED.
        calls = self.truth.query('rc72_n7_cleanup_call',preparation_id=preparation_id)
        if len(calls) != 2 or any(not r.get('runtime_signature') for r in calls):
            raise ContractError('CONCLUSIVE_FAILURE_SIGNED_CLEANUP_REQUIRED')
        core = dict(purpose=KIND, release_id=p['release_id'], source_commit=p['source_commit'],
            mission_id=p['mission_id'], release_batch_id=p['release_batch_id'], preparation_id=preparation_id,
            case_id=p['case_id'], attempt_id=p['attempt_id'], workitem_id=p['workitem_id'],
            contract_id=c['contract_id'], contract_sha256=c['contract_sha256'],
            full_plan_case_ids=sorted(cases), source_case_sha256=cases[p['case_id']]['source_case_sha256'],
            case_snapshot=snapshot, actual_result=deepcopy(dispatch['raw_result']),
            oracles=deepcopy(c['oracles']), oracle_result=deepcopy(oracle),
            oracle_context=dict(contract_sha256=c['contract_sha256'],dispatch_id=dispatch['dispatch_id'],
                attempt_id=p['attempt_id'],receipt_sha256=dispatch['receipt_sha256']))
        return p,core

    def _rows(self, preparation_id):
        p = self.preparation._one('rc72_n7_execution_preparation',preparation_id=preparation_id)
        return [r for r in self.truth.query('rc7_evidence',mission_id=p['mission_id'],kind=KIND)
                if r.get('subject_refs') == [p['attempt_id'],p['case_id']]]

    def rows(self, preparation_id):
        from .rc72_ledger_lock import ledger_lock
        with ledger_lock(self.truth,busy='CONCLUSIVE_FAILURE_LEDGER_BUSY'):
            return self._rows(preparation_id)

    def build(self, preparation_id):
        from .rc72_ledger_lock import ledger_lock
        with ledger_lock(self.truth,busy='CONCLUSIVE_FAILURE_LEDGER_BUSY'):
            return self._build_locked(preparation_id)

    def _build_locked(self, preparation_id):
        existing = self._rows(preparation_id)
        if existing:
            admitted = self._audit_locked(preparation_id,allow_missing_canonical=True)
            p = self.preparation._one('rc72_n7_execution_preparation',preparation_id=preparation_id)
            self._canonical_proof(p,admitted['proof'],admitted['evidence_id'],admitted['content_ref'])
            return self._audit_locked(preparation_id)
        p,core = self._context(preparation_id)
        files = []
        total = 0
        for declared in core['case_snapshot']['evidence_declarations']:
            data = self.review._file_bytes(declared)
            total += len(data)
            if total > self.review.max_bundle_bytes:
                raise ContractError('CONCLUSIVE_FAILURE_EVIDENCE_SIZE_LIMIT')
            files.append((declared,data))
        captured = []
        self.review.capture_root.mkdir(parents=True,exist_ok=True)
        for declared,data in files:
            path = self.review.capture_root / (declared['sha256']+'.bin')
            self.review._capture(path,data,declared['sha256'])
            evidence_id = 'N7FILE-'+_hash([p['attempt_id'],declared['requirement'],declared['sha256']])[:24]
            ref = 'file://'+str(path)
            self.review.evidence._ensure('rc7_evidence','RC7_EVIDENCE_UPSERTED','evidence_id',dict(
                evidence_id=evidence_id,release_id=p['release_id'],mission_id=p['mission_id'],
                kind='N7_REQUIRED_EVIDENCE_FILE',source_ref='r1://artifact/'+core['case_snapshot']['dispatch_id'],
                content_ref=ref,content_hash=declared['sha256'],subject_refs=[p['attempt_id'],p['case_id']],
                evidence_requirement=declared['requirement'],artifact_version=1))
            self.review.evidence._ensure('evidence','EVIDENCE_UPSERTED','id',dict(
                id=evidence_id,release_id=p['release_id'],kind='N7_REQUIRED_EVIDENCE_FILE',ref=ref,
                source_artifact_ref=core['case_snapshot']['dispatch_id'],tc_id=p['case_id'],attempt_id=p['attempt_id'],artifact_version=1))
            captured.append(dict(evidence_id=evidence_id,requirement=declared['requirement'],sha256=declared['sha256'],
                size_bytes=len(data),content_ref=ref))
        core['captured_evidence'] = captured
        digest = _hash(core)
        proof = dict(core,proof_sha256=digest)
        proof['signature'] = self.preparation.authority._sign(proof)
        data = json.dumps(proof,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        file_digest = hashlib.sha256(data).hexdigest()
        path = self.review.capture_root/(file_digest+'.json')
        self.review._capture(path,data,file_digest)
        evidence_id = 'N7FAILEV-'+digest[:24]
        ref = 'file://'+str(path)
        self.review.evidence._ensure('rc7_evidence','RC7_EVIDENCE_UPSERTED','evidence_id',dict(
            evidence_id=evidence_id,release_id=p['release_id'],mission_id=p['mission_id'],kind=KIND,
            source_ref='r1://artifact/'+core['case_snapshot']['dispatch_id'],content_ref=ref,content_hash=file_digest,
            subject_refs=[p['attempt_id'],p['case_id']],artifact_version=1))
        self._canonical_proof(p,core,evidence_id,ref)
        return self._audit_locked(preparation_id)

    def _canonical_proof(self, p, core, evidence_id, ref):
        self.review.evidence._ensure('evidence','EVIDENCE_UPSERTED','id',dict(
            id=evidence_id,release_id=p['release_id'],kind=KIND,ref=ref,
            source_artifact_ref=core['case_snapshot']['dispatch_id'],tc_id=p['case_id'],attempt_id=p['attempt_id'],artifact_version=1))

    def audit(self, preparation_id):
        from .rc72_ledger_lock import ledger_lock
        with ledger_lock(self.truth,busy='CONCLUSIVE_FAILURE_LEDGER_BUSY'):
            return self._audit_locked(preparation_id)

    def _audit_locked(self, preparation_id, *, allow_missing_canonical=False):
        p,expected = self._context(preparation_id)
        rows = self._rows(preparation_id)
        if len(rows) != 1:
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_NOT_UNIQUE')
        row = rows[0]
        path = Path(row['content_ref'][len('file://'):]) if row['content_ref'].startswith('file://') else None
        if (path is None or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != row['content_hash']):
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_BYTES_CHANGED')
        try:
            proof = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError) as exc:
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_ENCODING_INVALID') from exc
        if not isinstance(proof,dict):
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_ENCODING_INVALID')
        signed = {k:v for k,v in proof.items() if k!='signature'}
        if (not isinstance(proof.get('signature'),str)
                or not hmac.compare_digest(proof['signature'],self.preparation.authority._sign(signed))):
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_SIGNATURE_INVALID')
        core = {k:v for k,v in signed.items() if k!='proof_sha256'}
        if (any(core.get(k)!=v for k,v in expected.items()) or _hash(core)!=proof['proof_sha256']
                or row['evidence_id']!='N7FAILEV-'+proof['proof_sha256'][:24]
                or row['source_ref']!='r1://artifact/'+expected['case_snapshot']['dispatch_id']
                or row['content_ref']!='file://'+str(self.review.capture_root/(row['content_hash']+'.json'))
                or row['release_id']!=p['release_id']):
            raise ContractError('CONCLUSIVE_FAILURE_PROOF_SCOPE_CHANGED')
        declared = {r['requirement']:r for r in expected['case_snapshot']['evidence_declarations']}
        captured = proof['captured_evidence']
        if len(captured)!=len(declared) or {r['requirement'] for r in captured}!=set(declared):
            raise ContractError('CONCLUSIVE_FAILURE_CAPTURE_DENOMINATOR_CHANGED')
        for r in captured:
            expected_id = 'N7FILE-'+_hash([p['attempt_id'],r['requirement'],r['sha256']])[:24]
            expected_ref = 'file://'+str(self.review.capture_root/(r['sha256']+'.bin'))
            file = Path(expected_ref[len('file://'):])
            ev = self.preparation._one('rc7_evidence',evidence_id=expected_id)
            canonical = self.preparation._one('evidence',id=expected_id)
            if (r['evidence_id']!=expected_id or r['content_ref']!=expected_ref
                    or r['sha256']!=declared[r['requirement']]['sha256'] or file.is_symlink() or not file.is_file()
                    or len(file.read_bytes())!=r['size_bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=r['sha256']
                    or ev.get('content_hash')!=r['sha256'] or ev.get('content_ref')!=expected_ref
                    or ev.get('subject_refs')!=[p['attempt_id'],p['case_id']]
                    or ev.get('kind')!='N7_REQUIRED_EVIDENCE_FILE' or ev.get('evidence_requirement')!=r['requirement']
                    or canonical.get('ref')!=expected_ref or canonical.get('attempt_id')!=p['attempt_id']
                    or canonical.get('tc_id')!=p['case_id'] or canonical.get('release_id')!=p['release_id']):
                raise ContractError('CONCLUSIVE_FAILURE_CAPTURE_BYTES_OR_SCOPE_CHANGED')
        canonicals = self.truth.query('evidence',id=row['evidence_id'])
        if not canonicals and allow_missing_canonical:
            return dict(proof=proof,evidence_id=row['evidence_id'],content_ref=row['content_ref'],content_sha256=row['content_hash'])
        canonical = self.preparation._one('evidence',id=row['evidence_id'])
        if (canonical.get('ref')!=row['content_ref'] or canonical.get('attempt_id')!=p['attempt_id']
                or canonical.get('tc_id')!=p['case_id'] or canonical.get('release_id')!=p['release_id']
                or canonical.get('kind')!=KIND
                or canonical.get('source_artifact_ref')!=expected['case_snapshot']['dispatch_id']):
            raise ContractError('CONCLUSIVE_FAILURE_CANONICAL_PROOF_CHANGED')
        return dict(proof=proof,evidence_id=row['evidence_id'],content_ref=row['content_ref'],content_sha256=row['content_hash'])
