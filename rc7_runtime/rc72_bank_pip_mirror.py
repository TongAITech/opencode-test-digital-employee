"""Owned native user-mirror execution receipts; not detached caller PASS input.

The controller retains the signing authority. Pip receives only the real user's
configuration and an owned installation target. Unknown executions never replay.
"""
from copy import deepcopy
import hashlib,hmac,json,os,time
from pathlib import Path
from rc6_runtime import contracts,truth as registry
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_ledger_lock import ledger_lock
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay

_KIND='rc72_bank_pip_mirror_execution';_EVENT='RC72_BANK_PIP_MIRROR_EXECUTION_UPSERTED'
_PURPOSE='NATIVE_BANK_PC_PIP_MIRROR_EXECUTION'


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _validate(payload):
    row=deepcopy(payload)
    for key in ('execution_id','binding_id','release_id','mission_id','release_batch_id','source_commit','signature'):
        contracts._require_str(row,key)
    if (row.get('purpose')!=_PURPOSE or row.get('state') not in {'IN_FLIGHT','RETURNED','UNKNOWN'}
            or row.get('mode') not in {'BANK_FIELD','ENGINEERING'} or type(row.get('attempt')) is not int
            or not 1<=row['attempt']<=3 or not isinstance(row.get('binding'),dict)):
        raise contracts.DomainValidationError('BANK_PIP_MIRROR_NATIVE_RECEIPT_INVALID')
    if any(key in row for key in ('field_verified','bank_final','node_pass','q7_pass')):
        raise contracts.DomainValidationError('BANK_PIP_MIRROR_NATIVE_PROMOTION_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row));return row


def install_overlay():
    install_rc7_truth_overlay();install_rc72_truth_overlay()
    contracts.VALIDATORS[_KIND]=_validate;registry.EVENT_TYPES[_EVENT]=(_KIND,'execution_id')
    registry.IDENTITY_FIELDS[_KIND]='execution_id';registry.BUCKETS[_KIND]='rc72_bank_pip_mirror_executions'


class NativeBankPipMirrorService:
    def __init__(self,truth,*,release_id,source_commit,authority,package_root,archive,field_config,evidence_root):
        if not isinstance(authority,RC72AuthorityRuntime):raise ContractError('BANK_PIP_MIRROR_NATIVE_AUTHORITY_REQUIRED')
        if not isinstance(source_commit,str) or len(source_commit)!=40 or any(c not in '0123456789abcdef' for c in source_commit):
            raise ContractError('BANK_PIP_MIRROR_EXACT_SOURCE_REQUIRED')
        install_overlay();self.truth,self.release_id,self.source_commit,self.authority=truth,release_id,source_commit,authority
        self.root,self.archive,self.config,self.evidence=map(lambda p:Path(p).resolve(),(package_root,archive,field_config,evidence_root))

    def _one(self,kind,**filters):
        rows=self.truth.query(kind,**filters)
        if len(rows)!=1:raise ContractError('BANK_PIP_MIRROR_TRUTH_NOT_UNIQUE:'+kind)
        return rows[0]

    def _signed(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        if not isinstance(row.get('signature'),str) or not hmac.compare_digest(row['signature'],self.authority._sign(raw)):
            raise ContractError('BANK_PIP_MIRROR_EXECUTION_SIGNATURE_INVALID')
        return raw

    def _persist(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        old=self.truth.query(_KIND,execution_id=raw['execution_id'])
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=old[0]['artifact_version']+1 if old else 1))
        return self._one(_KIND,execution_id=raw['execution_id'])

    def _binding(self,batch_id,mode,bridge):
        from rc7_release.bank_pc_pip_mirror_probe import windows_user_appdata,prepare_environment
        batch=self._one('rc72_release_batch',release_batch_id=batch_id)
        if batch['release_id']!=self.release_id:raise ContractError('BANK_PIP_MIRROR_RELEASE_MISMATCH')
        if (self.root/'SOURCE_COMMIT').read_text(encoding='utf-8').strip()!=self.source_commit:
            raise ContractError('BANK_PIP_MIRROR_PACKAGE_SOURCE_MISMATCH')
        _,config,discovery=prepare_environment(windows_user_appdata(),os.environ,bridge=bridge)
        full=(self.root/'PACKAGE_MANIFEST.json').is_file()
        if full:
            from rc7_release.rc72_package import verify_package
            from rc7_release.rc72_complete_payload_inventory import verify_inventory
            verify_package(self.root,expected_source_commit=self.source_commit);verify_inventory(self.root)
        elif mode=='BANK_FIELD':raise ContractError('BANK_PIP_MIRROR_FULL_PACKAGE_REQUIRED')
        return dict(release_id=self.release_id,source_commit=self.source_commit,mission_id=batch['mission_id'],
            release_batch_id=batch_id,package_root=str(self.root),archive_path=str(self.archive),archive_sha256=_file_sha(self.archive),
            field_config_path=str(self.config),field_config_sha256=_file_sha(self.config),user_config_path=str(config),
            user_config_sha256=discovery['user_config_sha256'],mode=mode,bridge_user_config=bridge,full_package_verified=full)

    def _marker(self,row):
        path=self.evidence/row['execution_id']/'controller-result.json'
        try:path.resolve().relative_to(self.evidence)
        except ValueError:raise ContractError('BANK_PIP_MIRROR_NATIVE_RESULT_OUTSIDE_OWNED_ROOT') from None
        if path.is_symlink() or not path.is_file():raise ContractError('BANK_PIP_MIRROR_NATIVE_RESULT_REQUIRED')
        envelope=json.loads(path.read_text(encoding='utf-8'));raw={k:v for k,v in envelope.items() if k!='signature'}
        if (not isinstance(envelope.get('signature'),str) or not hmac.compare_digest(envelope['signature'],self.authority._sign(raw))
                or raw.get('execution_id')!=row['execution_id'] or raw.get('binding')!=row['binding']):
            raise ContractError('BANK_PIP_MIRROR_RESULT_SIGNATURE_OR_SCOPE_INVALID')
        if row.get('result_sha256') and row['result_sha256']!=_file_sha(path):
            raise ContractError('BANK_PIP_MIRROR_RESULT_CHANGED')
        return path,raw

    def _proof(self,row,*,require_field):
        raw=self._signed(row);path,envelope=self._marker(raw);proof=envelope.get('proof',{})
        if envelope.get('status')!='PASS' or proof.get('status')!='PASS':
            raise ContractError('BANK_PIP_MIRROR_NATIVE_NOT_PASS')
        binding=raw['binding']
        if (proof.get('gate')!='BANK_PC_PIP_MIRROR_GATE' or proof.get('schema')!='RC72_BANK_PC_PIP_MIRROR_V1'
                or proof.get('qualification_scope')!=('BANK_PC_USER_MIRROR_FIELD_FACT' if raw['mode']=='BANK_FIELD'
                    else 'ENGINEERING_WINDOWS_USER_MIRROR_SIMULATION')):
            raise ContractError('BANK_PIP_MIRROR_NATIVE_PROOF_PROTOCOL_INVALID')
        if (not isinstance(proof.get('python_version'),str) or not proof['python_version']
                or not isinstance(proof.get('pip_version'),str) or not proof['pip_version']
                or proof.get('platform_family')!='Windows'):
            raise ContractError('BANK_PIP_MIRROR_NATIVE_INTERPRETER_PLATFORM_PROOF_REQUIRED')
        expected=dict(source_commit=self.source_commit,archive_sha256=binding['archive_sha256'],package_root=binding['package_root'])
        if any(proof.get(k)!=v for k,v in expected.items()):raise ContractError('BANK_PIP_MIRROR_NATIVE_PROOF_CHANGED')
        if (proof.get('discovery',{}).get('user_config_sha256')!=binding['user_config_sha256']
                or proof.get('bank_final') is not False or proof.get('field_verified') is not False):
            raise ContractError('BANK_PIP_MIRROR_NATIVE_CONFIG_OR_SCOPE_CHANGED')
        expected_field=raw['mode']=='BANK_FIELD'
        if proof.get('bank_pc_mirror_field_fact') is not expected_field:
            raise ContractError('BANK_PIP_MIRROR_NATIVE_FACT_SCOPE_CHANGED')
        if require_field and (not expected_field or binding['full_package_verified'] is not True):
            raise ContractError('BANK_PIP_MIRROR_ENGINEERING_NOT_FIELD')
        private=path.parent/'probe/private'
        files=proof.get('private_evidence_sha256')
        required={name+'.'+suffix+'.log' for name in ('pip-version','provenance','config-debug','config-list','mirror-install','same-interpreter-import','provenance-after') for suffix in ('stdout','stderr')}|{'install-report.json'}
        if not isinstance(files,dict) or not required.issubset(files):raise ContractError('BANK_PIP_MIRROR_NATIVE_EVIDENCE_REQUIRED')
        for name,digest in files.items():
            if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name:
                raise ContractError('BANK_PIP_MIRROR_PRIVATE_EVIDENCE_PATH_INVALID')
            file=private/name
            try:file.resolve().relative_to(self.evidence)
            except ValueError:raise ContractError('BANK_PIP_MIRROR_PRIVATE_EVIDENCE_OUTSIDE_ROOT') from None
            if file.is_symlink() or not file.is_file() or _file_sha(file)!=digest:
                raise ContractError('BANK_PIP_MIRROR_PRIVATE_EVIDENCE_CHANGED')
        return dict(execution_id=raw['execution_id'],binding_id=raw['binding_id'],source_commit=raw['source_commit'],
            mission_id=raw['mission_id'],release_batch_id=raw['release_batch_id'],release_id=raw['release_id'],
            mode=raw['mode'],full_package_verified=binding['full_package_verified'],archive_sha256=binding['archive_sha256'],
            result_ref='file://'+str(path),result_sha256=_file_sha(path),status='PASS',bank_pc_mirror_field_fact=expected_field)

    def _history(self,row):
        history=self.truth.projection.history(_KIND,row['execution_id'])
        history=sorted(history,key=lambda r:r['artifact_version'])
        if not history or history[0]['state']!='IN_FLIGHT' or history[0]['artifact_version']!=1:
            raise ContractError('BANK_PIP_MIRROR_NATIVE_INTENT_REQUIRED')
        state='IN_FLIGHT'
        for version,observed in enumerate(history,1):
            self._signed(observed)
            if (observed['artifact_version']!=version or any(observed.get(key)!=row.get(key)
                    for key in ('execution_id','binding_id','binding','mode','attempt','parent_execution_id','started_at'))):
                raise ContractError('BANK_PIP_MIRROR_NATIVE_HISTORY_CHANGED')
            following=observed['state']
            if (state=='RETURNED' and following!='RETURNED') or (state=='UNKNOWN' and following=='IN_FLIGHT'):
                raise ContractError('BANK_PIP_MIRROR_NATIVE_HISTORY_INVALID')
            state=following
        if history[-1]!=row:raise ContractError('BANK_PIP_MIRROR_NATIVE_CURRENT_HISTORY_REQUIRED')

    def _chain(self,rows,binding,bid):
        if [r['attempt'] for r in rows]!=list(range(1,len(rows)+1)):
            raise ContractError('BANK_PIP_MIRROR_ATTEMPT_CHAIN_INVALID')
        previous=None
        for index,row in enumerate(rows):
            self._signed(row);self._history(row)
            if (row['binding']!=binding or row['binding_id']!=bid or row['mode']!=binding['mode']
                    or row['execution_id']!='PIP-EXEC-'+_hash([bid,row['attempt']])[:24]
                    or row.get('parent_execution_id')!=previous):
                raise ContractError('BANK_PIP_MIRROR_ATTEMPT_CHAIN_CHANGED')
            if index<len(rows)-1:
                _,result=self._marker(row)
                if row['state']!='RETURNED' or result.get('status')!='FAIL':
                    raise ContractError('BANK_PIP_MIRROR_RETRY_PREDECESSOR_NOT_FAILED')
            previous=row['execution_id']

    def audit(self,*,execution_id,release_batch_id,require_field=True):
        """Cold historical verification; does not invoke pip or revive a lease."""
        with ledger_lock(self.truth,busy='BANK_PIP_MIRROR_LEDGER_BUSY'):
            return self._audit_locked(execution_id=execution_id,release_batch_id=release_batch_id,require_field=require_field)

    def _audit_locked(self,*,execution_id,release_batch_id,require_field=True):
        row=self._one(_KIND,execution_id=execution_id);self._signed(row)
        batch=self._one('rc72_release_batch',release_batch_id=release_batch_id)
        if (row['release_id']!=self.release_id or row['source_commit']!=self.source_commit
                or row['release_batch_id']!=release_batch_id or row['mission_id']!=batch['mission_id']
                or batch['release_id']!=self.release_id or row['binding']['package_root']!=str(self.root)
                or row['binding']['archive_path']!=str(self.archive) or row['binding']['field_config_path']!=str(self.config)):
            raise ContractError('BANK_PIP_MIRROR_AUDIT_SCOPE_CHANGED')
        self._chain(sorted(self.truth.query(_KIND,binding_id=row['binding_id']),key=lambda r:r['attempt']),row['binding'],row['binding_id'])
        if _file_sha(self.archive)!=row['binding']['archive_sha256'] or _file_sha(self.config)!=row['binding']['field_config_sha256']:
            raise ContractError('BANK_PIP_MIRROR_CURRENT_PACKAGE_OR_POLICY_CHANGED')
        if (self.root/'SOURCE_COMMIT').read_text(encoding='utf-8').strip()!=self.source_commit:
            raise ContractError('BANK_PIP_MIRROR_CURRENT_SOURCE_CHANGED')
        if row['state']!='RETURNED':raise ContractError('BANK_PIP_MIRROR_NATIVE_NOT_RETURNED')
        return self._proof(row,require_field=require_field)

    def run(self,*,release_batch_id,engineering=False,bridge_user_config=False,retry_returned_failure=False):
        from rc7_release.bank_pc_pip_mirror_probe import qualify
        if any(type(value) is not bool for value in (engineering,bridge_user_config,retry_returned_failure)):
            raise ContractError('BANK_PIP_MIRROR_EXECUTION_OPTIONS_INVALID')
        # Generic hosted engineering cannot be upgraded into a bank Field fact.
        engineering=bool(engineering or os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted')
        mode='ENGINEERING' if engineering else 'BANK_FIELD'
        with ledger_lock(self.truth,busy='BANK_PIP_MIRROR_LEDGER_BUSY'):
            binding=self._binding(release_batch_id,mode,bridge_user_config);bid='PIP-BIND-'+_hash(binding)[:24]
            rows=self.truth.query(_KIND,binding_id=bid)
            if len({r['attempt'] for r in rows})!=len(rows):raise ContractError('BANK_PIP_MIRROR_ATTEMPT_NOT_UNIQUE')
            rows=sorted(rows,key=lambda row:row['attempt']);attempt=1
            self._chain(rows,binding,bid)
            if rows:
                previous=rows[-1];self._signed(previous)
                if previous['binding']!=binding:raise ContractError('BANK_PIP_MIRROR_BINDING_CHANGED')
                marker=self.evidence/previous['execution_id']/'controller-result.json'
                if previous['state'] in {'IN_FLIGHT','UNKNOWN'} and marker.is_file():
                    path,result=self._marker(previous)
                    previous=self._persist(dict(previous,state='RETURNED',result_sha256=_file_sha(path),returned_at=result['observed_at']))
                if previous['state']=='RETURNED':
                    _,result=self._marker(previous)
                    if result['status']=='PASS':return self._proof(previous,require_field=not engineering)
                    if not retry_returned_failure:return dict(status='HOLD',reason='BANK_PIP_MIRROR_RETURNED_FAILURE',execution_id=previous['execution_id'])
                    attempt=previous['attempt']+1
                    if attempt>3:return dict(status='HOLD',reason='BANK_PIP_MIRROR_RETRY_LIMIT',execution_id=previous['execution_id'])
                else:return dict(status='HOLD',reason='BANK_PIP_MIRROR_UNKNOWN_NO_REPLAY',execution_id=previous['execution_id'])
            eid='PIP-EXEC-'+_hash([bid,attempt])[:24]
            row=self._persist(dict(execution_id=eid,binding_id=bid,purpose=_PURPOSE,release_id=self.release_id,
                mission_id=binding['mission_id'],release_batch_id=release_batch_id,source_commit=self.source_commit,
                binding=binding,mode=mode,attempt=attempt,parent_execution_id=rows[-1]['execution_id'] if rows else None,state='IN_FLIGHT',started_at=int(time.time())))
        directory=self.evidence/eid;directory.mkdir(parents=True,exist_ok=True);path=directory/'controller-result.json'
        try:
            try:
                proof=qualify(self.root,self.archive,json.loads(self.config.read_text(encoding='utf-8')),
                    directory/'probe',bridge=bridge_user_config,engineering=engineering)
                if proof.get('status')!='PASS':raise ContractError('BANK_PIP_MIRROR_QUALIFIER_NOT_PASS')
                result=dict(execution_id=eid,binding=binding,status='PASS',proof=proof,observed_at=int(time.time()))
            except Exception as exc:
                result=dict(execution_id=eid,binding=binding,status='FAIL',error_type=type(exc).__name__,observed_at=int(time.time()))
            envelope=dict(result,signature=self.authority._sign(result))
            with path.open('x',encoding='utf-8') as stream:
                stream.write(json.dumps(envelope,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
            with ledger_lock(self.truth,busy='BANK_PIP_MIRROR_LEDGER_BUSY'):
                current=self._one(_KIND,execution_id=eid);self._signed(current)
                if current['state']!='IN_FLIGHT' or current['binding']!=binding:raise ContractError('BANK_PIP_MIRROR_EXECUTION_CHANGED')
                row=self._persist(dict(current,state='RETURNED',result_sha256=_file_sha(path),returned_at=result['observed_at']))
            if result['status']=='FAIL':return dict(status='HOLD',reason='BANK_PIP_MIRROR_NATIVE_QUALIFICATION_FAILED',execution_id=eid)
            return self.audit(execution_id=eid,release_batch_id=release_batch_id,require_field=not engineering)
        except BaseException:
            with ledger_lock(self.truth,busy='BANK_PIP_MIRROR_LEDGER_BUSY'):
                current=self._one(_KIND,execution_id=eid);self._signed(current)
                if current['state']=='IN_FLIGHT':self._persist(dict(current,state='UNKNOWN',interrupted_at=int(time.time())))
            raise


install_overlay()
