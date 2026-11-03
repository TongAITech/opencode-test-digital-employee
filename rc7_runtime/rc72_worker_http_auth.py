"""Parent-only use of exact worker-owned, non-device-bound HTTP auth assets.

A bank AuthKeeper/4A exporter supplies one scoped asset per worker/attempt. The
runtime does not turn Captain credentials or a claimed role into authorization:
it checks the frozen N1 identity endpoint with the actual header before I/O.
Secrets stay in the parent; durable proof contains signed projected identity only.
"""
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler

from .models import ContractError
from .rc72_http_projection import map_response
from .rc72_n7_execution_admission import _hash

MODE='WORKER_HEADER'
PROTOCOL='RC72_WORKER_HTTP_AUTH_V1'
def _now():
    return int(time.time())


_SCOPE=('preparation_id','release_id','source_commit','mission_id','workitem_id',
        'attempt_id','worker_id','contract_id')


def _origin(url):
    parts=urlsplit(url)
    if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ContractError('WORKER_HTTP_AUTH_EXACT_TARGET_REQUIRED')
    try:
        return parts.scheme,parts.hostname,parts.port or (443 if parts.scheme=='https' else 80)
    except ValueError:
        raise ContractError('WORKER_HTTP_AUTH_EXACT_TARGET_REQUIRED') from None


def auth_spec(contract):
    profile=contract['environment'].get('target_profile',{})
    auth_id=profile.get('selectors',{}).get('auth_fact_id')
    facts=[r for r in profile.get('facts',[]) if r.get('kind')=='auth' and r.get('id')==auth_id]
    if (len(facts)!=1 or facts[0].get('source_ref') not in contract['authoritative_sources']
            or facts[0].get('attributes',{}).get('authentication_mode')!=MODE):
        raise ContractError('WORKER_HTTP_AUTH_FROZEN_N1_FACT_REQUIRED')
    spec=deepcopy(facts[0].get('attributes',{}).get('worker_http_auth'))
    if (not isinstance(spec,dict) or set(spec)!={'asset_ref','principal','roles','identity_probe','device_bound'}
            or spec['device_bound'] is not False
            or any(not isinstance(spec[k],str) or not spec[k].strip() for k in ('asset_ref','principal'))
            or not isinstance(spec['roles'],list) or not spec['roles']
            or any(not isinstance(v,str) or not v.strip() or '*' in v for v in spec['roles'])
            or len(set(spec['roles']))!=len(spec['roles'])):
        raise ContractError('WORKER_HTTP_AUTH_NON_DEVICE_BOUND_SCOPE_REQUIRED')
    probe=spec['identity_probe']
    if (not isinstance(probe,dict) or set(probe)!={'url','principal_path','roles_path'}
            or any(not isinstance(probe[k],str) or not probe[k].startswith('$json.') for k in ('principal_path','roles_path'))
            or not isinstance(probe['url'],str) or _origin(probe['url'])!=_origin(contract['endpoint']['url'])):
        raise ContractError('WORKER_HTTP_AUTH_APPROVED_IDENTITY_PROBE_REQUIRED')
    return facts[0]['id'],spec


def business_role(preparation,p):
    plan=preparation._one('rc72_n7_execution_plan',plan_id=p['plan_id'])
    snapshot=preparation._one('rc72_decomposition_snapshot',snapshot_id=plan['snapshot_id'])
    cases=[r for r in snapshot['planning_cases'] if r['case_id']==p['case_id']]
    if len(cases)!=1 or not isinstance(cases[0].get('auth_role'),str) or not cases[0]['auth_role'].strip():
        raise ContractError('WORKER_HTTP_AUTH_ORIGINAL_CASE_ROLE_REQUIRED')
    return cases[0]['auth_role']


def verify_auth_receipt(preparation,p,contract,receipt):
    """Historical native observation audit; never reads/restores a live secret."""
    if not isinstance(receipt,dict):
        raise ContractError('WORKER_HTTP_AUTH_OBSERVATION_REQUIRED')
    fields={'purpose','auth_fact_id','auth_spec_sha256','asset_ref','principal','role',
            'roles','issued_at','expires_at','observed_at','secret_binding',
            'identity_response_sha256','identity_status','signature','contract_sha256',*_SCOPE}
    if set(receipt)!=fields:
        raise ContractError('WORKER_HTTP_AUTH_OBSERVATION_FIELDS_INVALID')
    raw={k:v for k,v in receipt.items() if k!='signature'}
    if not isinstance(receipt['signature'],str) or not hmac.compare_digest(receipt['signature'],preparation.authority._sign(raw)):
        raise ContractError('WORKER_HTTP_AUTH_OBSERVATION_SIGNATURE_INVALID')
    fact_id,spec=auth_spec(contract)
    role=business_role(preparation,p)
    times=[receipt.get(k) for k in ('issued_at','observed_at','expires_at')]
    if (any(not isinstance(v,int) or isinstance(v,bool) for v in times)
            or not times[0]<=times[1]<times[2]
            or receipt['purpose']!=PROTOCOL
            or any(receipt.get(k)!=p[k] for k in _SCOPE)
            or receipt['contract_sha256']!=contract['contract_sha256']
            or receipt['auth_fact_id']!=fact_id or receipt['auth_spec_sha256']!=_hash(spec)
            or receipt['asset_ref']!=spec['asset_ref'] or receipt['principal']!=spec['principal']
            or receipt['role']!=role or role not in spec['roles']
            or receipt['roles']!=sorted(spec['roles']) or receipt['identity_status']!=200
            or any(not isinstance(receipt.get(k),str) or len(receipt[k])!=64
                   or any(ch not in '0123456789abcdef' for ch in receipt[k])
                   for k in ('secret_binding','identity_response_sha256'))):
        raise ContractError('WORKER_HTTP_AUTH_OBSERVATION_SCOPE_INVALID')
    return deepcopy(receipt)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


def validate_asset_root(value, *, forbidden_roots):
    """An explicit host export directory, disjoint from carried/Worker evidence.

    Validation never reads credentials, creates directories or asserts readiness.
    """
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ContractError('MISSION_HTTP_AUTH_ASSET_ROOT_REQUIRED')
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ContractError('MISSION_HTTP_AUTH_ASSET_DIRECTORY_REQUIRED')
    for item in forbidden_roots:
        other = Path(item).resolve()
        if root == other or root in other.parents or other in root.parents:
            raise ContractError('MISSION_HTTP_AUTH_PRIVATE_HOST_DIRECTORY_REQUIRED')
    return root


class WorkerHTTPAuthAssetProvider:
    """Reads bank-owned worker exports; never accepts an Agent's secret argument.

    Asset path is <configured root>/<runtime worker>/<runtime attempt>.json.
    Exporter integration/real 4A login stays a bank host binding; this class
    verifies its actual HTTP identity, not the exporter's success boolean.
    """
    def __init__(self,preparation,*,asset_root):
        from .rc72_n7_execution_preparation import ExecutionPreparationService
        if not isinstance(preparation,ExecutionPreparationService):
            raise ContractError('WORKER_HTTP_AUTH_NATIVE_PREPARATION_REQUIRED')
        self.preparation=preparation
        self.root=Path(asset_root).expanduser().resolve()
        self._observed={}

    def _asset(self,p,contract):
        fact_id,spec=auth_spec(contract)
        role=business_role(self.preparation,p)
        if role=='ANONYMOUS' or role not in spec['roles']:
            raise ContractError('WORKER_HTTP_AUTH_CASE_ROLE_MISMATCH')
        if any(Path(p[k]).name!=p[k] or p[k] in {'.','..'} or '\\' in p[k] for k in ('worker_id','attempt_id')):
            raise ContractError('WORKER_HTTP_AUTH_ASSET_SCOPE_PATH_INVALID')
        worker=self.root/p['worker_id']
        path=worker/(p['attempt_id']+'.json')
        if worker.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
            raise ContractError('WORKER_HTTP_AUTH_SCOPED_ASSET_REQUIRED')
        try:
            with path.open('rb') as stream:
                data=stream.read(65537)
            if len(data)>65536:
                raise ContractError('WORKER_HTTP_AUTH_ASSET_TOO_LARGE')
            asset=json.loads(data.decode('utf-8'))
        except (OSError,ValueError,UnicodeError):
            raise ContractError('WORKER_HTTP_AUTH_ASSET_UNREADABLE') from None
        fields={'schema','auth_asset_ref','principal','role','issued_at','expires_at','headers',*_SCOPE}
        if (not isinstance(asset,dict) or set(asset)!=fields or asset['schema']!=PROTOCOL
                or any(asset.get(k)!=p[k] for k in _SCOPE)
                or asset['auth_asset_ref']!=spec['asset_ref'] or asset['principal']!=spec['principal'] or asset['role']!=role):
            raise ContractError('WORKER_HTTP_AUTH_ASSET_IDENTITY_MISMATCH')
        now=_now()
        if (any(not isinstance(asset.get(k),int) or isinstance(asset[k],bool) for k in ('issued_at','expires_at'))
                or not asset['issued_at']<=now<asset['expires_at']):
            raise ContractError('WORKER_HTTP_AUTH_ASSET_EXPIRED_OR_NOT_ISSUED')
        headers=asset['headers']
        if (not isinstance(headers,dict) or set(headers)!={'Authorization'}
                or not isinstance(headers['Authorization'],str) or not headers['Authorization'].strip()
                or len(headers['Authorization'])>16384 or any(ch in headers['Authorization'] for ch in ('\r','\n','\x00'))):
            raise ContractError('WORKER_HTTP_AUTH_EXACT_AUTHORIZATION_HEADER_REQUIRED')
        binding=self.preparation.authority._sign(dict(purpose='WORKER_HTTP_SECRET_BINDING',
            **{k:p[k] for k in _SCOPE},asset_sha256=hashlib.sha256(data).hexdigest()))
        return asset,fact_id,spec,binding

    def assert_live(self,p,contract):
        _asset,_fact,_spec,binding=self._asset(p,contract)
        observed=self._observed.get(p['preparation_id'])
        if observed is not None and not hmac.compare_digest(binding,observed['secret_binding']):
            raise ContractError('WORKER_HTTP_AUTH_ASSET_CHANGED_DURING_EFFECT')

    def observe(self,gate):
        from .rc72_native_http_gate import NativeHTTPGate
        if not isinstance(gate,NativeHTTPGate) or gate.preparation is not self.preparation:
            raise ContractError('WORKER_HTTP_AUTH_LIVE_NATIVE_GATE_REQUIRED')
        p,contract=gate.p,gate.contract
        with gate._decision():
            gate._actor()
            asset,fact_id,spec,binding=self._asset(p,contract)
        request=Request(spec['identity_probe']['url'],headers=dict(asset['headers']),method='GET')
        try:
            opener=build_opener(ProxyHandler({}),_NoRedirect())
            try:
                response=opener.open(request,timeout=gate.timeout)
            except HTTPError as exc:
                response=exc
            with response:
                status=response.code
                body=response.read(65537)
            if status!=200 or len(body)>65536:
                raise ContractError('WORKER_HTTP_AUTH_IDENTITY_NOT_VERIFIED')
            identity=map_response(dict(principal=spec['identity_probe']['principal_path'],
                roles=spec['identity_probe']['roles_path']),status,json.loads(body.decode('utf-8')))
        except ContractError:
            raise
        except Exception:
            raise ContractError('WORKER_HTTP_AUTH_IDENTITY_PROBE_FAILED') from None
        if (identity['principal']!=spec['principal'] or not isinstance(identity['roles'],list)
                or any(not isinstance(v,str) for v in identity['roles'])
                or sorted(identity['roles'])!=sorted(spec['roles'])):
            raise ContractError('WORKER_HTTP_AUTH_ACTUAL_IDENTITY_OR_ROLE_MISMATCH')
        with gate._decision():
            gate._actor()
            current,_fact,_spec,current_binding=self._asset(p,contract)
            if not hmac.compare_digest(current_binding,binding):
                raise ContractError('WORKER_HTTP_AUTH_ASSET_CHANGED_DURING_PROBE')
            raw=dict(purpose=PROTOCOL,**{k:p[k] for k in _SCOPE},contract_sha256=contract['contract_sha256'],
                auth_fact_id=fact_id,auth_spec_sha256=_hash(spec),asset_ref=spec['asset_ref'],
                principal=identity['principal'],role=asset['role'],roles=sorted(identity['roles']),
                issued_at=asset['issued_at'],expires_at=asset['expires_at'],observed_at=_now(),
                secret_binding=binding,identity_response_sha256=hashlib.sha256(body).hexdigest(),identity_status=status)
            receipt=dict(raw,signature=self.preparation.authority._sign(raw))
            verify_auth_receipt(self.preparation,p,contract,receipt)
            self._observed[p['preparation_id']]=receipt
        return deepcopy(asset['headers']),deepcopy(receipt)

    def release(self,p):
        self._observed.pop(p['preparation_id'],None)
