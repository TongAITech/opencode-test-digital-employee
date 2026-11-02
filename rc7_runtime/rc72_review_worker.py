"""Standalone deterministic, read-only evidence reviewer (stdlib only)."""
import hashlib
import json
from pathlib import Path
import sys


def review(path):
    request = json.loads(Path(path).read_text(encoding='utf-8'))
    bundle = request['bundle']
    core = {key: value for key, value in bundle.items() if key not in
            {'bundle_id', 'bundle_sha256', 'artifact_type', 'artifact_version'}}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    failures, observed = [], []
    if digest != bundle['bundle_sha256'] or bundle['known_gaps']:
        failures.append('BUNDLE_IDENTITY_OR_FORMAL_GAPS')
    for case in bundle['case_results']:
        required = {row['requirement'] for row in case['evidence_declarations']}
        if required != {row['requirement'] for row in case['captured_evidence']}:
            failures.append('EVIDENCE_DENOMINATOR')
        for row in case['captured_evidence']:
            ref = row['content_ref']
            file = Path(ref[len('file://'):]) if ref.startswith('file://') else None
            if file is None or not file.is_file() or file.is_symlink():
                failures.append('EVIDENCE_FILE_MISSING')
                continue
            raw = file.read_bytes()
            if len(raw) != row['size_bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                failures.append('EVIDENCE_FILE_DIGEST')
            observed.append(row['evidence_id'])
    return dict(bundle_id=bundle['bundle_id'], bundle_sha256=bundle['bundle_sha256'],
                review_id=request['review_id'], reviewer_worker_id=request['reviewer_worker_id'],
                reviewer_session_id=request['reviewer_session_id'], passed=not failures,
                observed_files=sorted(observed), failures=failures)


if __name__ == '__main__':
    result = review(sys.argv[1])
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['passed'] else 2)
