"""Trusted prior Field snapshots for engineering tests of later product nodes.

These are synthetic upstream prerequisites, like fixture Q3/Human approvals.
They are NOT actual Windows/mirror evidence. No production switch or callback
accepts these fixtures; this module is not copied into the portable package.
Actual mirror execution is independently tested by the Windows component job.
"""
import hashlib,json
from pathlib import Path
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_bank_pip_mirror import NativeBankPipMirrorService
from rc7_runtime.rc72_n7_execution_admission import _hash

_KEY=b'engineering-fixture-prior-bank-field-boundary'


def provider(truth,*,release_batch_id=None,source_commit):
    batches=truth.query('rc72_release_batch',**({'release_batch_id':release_batch_id} if release_batch_id is not None else {}))
    if len(batches)!=1:return None
    batch=batches[0];release_batch_id=batch['release_batch_id']
    home=Path(truth.store.path).parent/'prior-field-fixture'/hashlib.sha256((release_batch_id+source_commit).encode()).hexdigest()[:16]
    return NativeBankPipMirrorService(truth,release_id=batch['release_id'],source_commit=source_commit,
        authority=RC72AuthorityRuntime(_KEY),package_root=home/'package',archive=home/'archive.zip',
        field_config=home/'field-policy.json',evidence_root=home/'evidence')


def seed(truth,*,release_batch_id,source_commit):
    service=provider(truth,release_batch_id=release_batch_id,source_commit=source_commit)
    batch=truth.query('rc72_release_batch',release_batch_id=release_batch_id)[0]
    existing=truth.query('rc72_bank_pip_mirror_execution',release_batch_id=release_batch_id,source_commit=source_commit)
    if existing:return service,service.audit(execution_id=existing[-1]['execution_id'],release_batch_id=release_batch_id)
    service.root.mkdir(parents=True);(service.root/'SOURCE_COMMIT').write_text(source_commit)
    service.archive.write_bytes(b'synthetic prior field archive binding, not an actual package')
    service.config.write_text('{"purpose":"synthetic upstream Field prerequisite"}')
    user=service.root.parent/'prior-user-pip.ini';user.write_text('synthetic trusted previous user config')
    digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    binding=dict(release_id=batch['release_id'],source_commit=source_commit,mission_id=batch['mission_id'],release_batch_id=release_batch_id,
        package_root=str(service.root),archive_path=str(service.archive),archive_sha256=digest(service.archive),
        field_config_path=str(service.config),field_config_sha256=digest(service.config),user_config_path=str(user),user_config_sha256=digest(user),
        mode='BANK_FIELD',bridge_user_config=False,full_package_verified=True)
    bid='PIP-BIND-'+_hash(binding)[:24];eid='PIP-EXEC-'+_hash([bid,1])[:24]
    row=service._persist(dict(execution_id=eid,binding_id=bid,purpose='NATIVE_BANK_PC_PIP_MIRROR_EXECUTION',
        release_id=batch['release_id'],mission_id=batch['mission_id'],release_batch_id=release_batch_id,source_commit=source_commit,
        binding=binding,mode='BANK_FIELD',attempt=1,parent_execution_id=None,state='IN_FLIGHT',started_at=1))
    directory=service.evidence/eid;private=directory/'probe/private';private.mkdir(parents=True)
    files={name+'.'+suffix+'.log' for name in ('pip-version','provenance','config-debug','config-list','mirror-install','same-interpreter-import','provenance-after')
        for suffix in ('stdout','stderr')}|{'install-report.json'}
    for name in files:(private/name).write_text('synthetic prior Field protocol data; not observed bank output')
    proof=dict(gate='BANK_PC_PIP_MIRROR_GATE',schema='RC72_BANK_PC_PIP_MIRROR_V1',status='PASS',source_commit=source_commit,
        archive_sha256=binding['archive_sha256'],package_root=str(service.root),qualification_scope='BANK_PC_USER_MIRROR_FIELD_FACT',python_version='3.11.0',pip_version='synthetic-prior-fixture',platform_family='Windows',
        discovery=dict(user_config_sha256=binding['user_config_sha256']),bank_pc_mirror_field_fact=True,field_verified=False,bank_final=False,
        private_evidence_sha256={name:digest(private/name) for name in files})
    result=dict(execution_id=eid,binding=binding,status='PASS',proof=proof,observed_at=2)
    marker=directory/'controller-result.json';marker.write_text(json.dumps(dict(result,signature=service.authority._sign(result)),sort_keys=True)+'\n')
    service._persist(dict(row,state='RETURNED',result_sha256=digest(marker),returned_at=2))
    return service,service.audit(execution_id=eid,release_batch_id=release_batch_id)


def bind_admissions(truth,*,release_batch_id,source_commit):
    service,proof=seed(truth,release_batch_id=release_batch_id,source_commit=source_commit)
    rows=truth.query('rc72_q7_admission',release_batch_id=release_batch_id,source_commit=source_commit)
    for row in rows:
        if row.get('bank_pip_mirror_proof')==proof:continue
        row.update(bank_pip_mirror_execution_id=proof['execution_id'],bank_pip_mirror_proof=proof,artifact_version=row['artifact_version']+1)
        truth.append_atomic('RC72_Q7_ADMISSION_UPSERTED',row)
    return service
