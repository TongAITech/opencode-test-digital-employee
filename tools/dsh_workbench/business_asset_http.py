"""B07 milestone HTTP seam; unsafe methods require trusted Host proof."""
import json
import re
from urllib.parse import parse_qs,unquote,urlsplit
from .business_assets import AssetStore
from .business_store import BusinessError


def asset_request(handler,identity,connection_factory,cursor_key):
    url=urlsplit(handler.path)
    match=re.fullmatch(r'/api/workbench/v1/projects/([^/]+)/batches/([^/]+)/assets(?:/([^/]+))?(/restore)?',url.path)
    if not match:raise BusinessError(404,'RESOURCE_NOT_FOUND')
    project,batch,asset=[unquote(x) if x else None for x in match.groups()[:3]]
    if any(x is not None and (not x or '/' in x) for x in (project,batch,asset)):raise BusinessError(400,'INVALID_ASSET_REQUEST')
    writing=handler.command!='GET'
    if writing and getattr(identity,'mutation_authorized',False) is not True:raise BusinessError(403,'MUTATION_AUTH_REQUIRED')
    with connection_factory() as connection:
        store=AssetStore(connection,cursor_key)
        # Do not parse an object's body or query before current project permission.
        with store._scope(identity.principal,project,writing):pass
        if handler.command=='GET':
            try:q=parse_qs(url.query,keep_blank_values=True,max_num_fields=400,strict_parsing=True) if url.query else {}
            except ValueError:raise BusinessError(400,'INVALID_ASSET_QUERY')
            allowed={'kind','requirement_ids','system_version_ids','sst_ids','due_from','due_to','include_retired','page_size','page_cursor'} if asset is None else {'revision','include_retired'}
            if set(q)-allowed or any(len(values)!=1 for key,values in q.items() if key not in ('requirement_ids','system_version_ids','sst_ids')):raise BusinessError(400,'INVALID_ASSET_QUERY')
            retired=q.get('include_retired',['false'])[0]
            if retired not in ('true','false'):raise BusinessError(400,'INVALID_ASSET_QUERY')
            if match[4]:raise BusinessError(405,'METHOD_NOT_ALLOWED')
            try:
                if asset:
                    result=store.get(identity.principal,project,batch,asset,revision=int(q['revision'][0]) if 'revision' in q else None,include_retired=retired=='true')
                else:
                    result=store.list(identity.principal,project,batch,kind=q.get('kind',[None])[0],requirement_ids=q.get('requirement_ids'),system_version_ids=q.get('system_version_ids'),sst_ids=q.get('sst_ids'),due_from=q.get('due_from',[None])[0],due_to=q.get('due_to',[None])[0],include_retired=retired=='true',page_size=int(q.get('page_size',['100'])[0]),page_cursor=q.get('page_cursor',[None])[0])
            except ValueError:raise BusinessError(400,'INVALID_ASSET_QUERY')
            return 200,result
        if url.query:raise BusinessError(400,'INVALID_ASSET_REQUEST')
        if handler.headers.get('Transfer-Encoding'):raise BusinessError(400,'INVALID_BODY')
        try:length=int(handler.headers.get('Content-Length',''))
        except ValueError:raise BusinessError(400,'INVALID_BODY')
        if not 0<length<=65536:raise BusinessError(400,'INVALID_BODY')
        if handler.headers.get_content_type()!='application/json':raise BusinessError(400,'INVALID_BODY')
        def unique_object(pairs):
            value={}
            for key,item in pairs:
                key.encode('utf-8')
                if isinstance(item,str):item.encode('utf-8')
                if key in value:raise ValueError('DUPLICATE_JSON_KEY')
                value[key]=item
            return value
        handler.connection.settimeout(5)
        try:
            raw=handler.rfile.read(length)
            if len(raw)!=length:raise ValueError('INCOMPLETE_BODY')
            body=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_object)
        except (ValueError,UnicodeError,RecursionError):raise BusinessError(400,'INVALID_BODY')
        action=None
        if handler.command=='POST' and asset is None:action='create'
        elif handler.command=='POST' and asset and match[4]:action='restore'
        elif handler.command=='PATCH' and asset and not match[4]:action='update'
        elif handler.command=='DELETE' and asset and not match[4]:action='retire'
        if action is None:raise BusinessError(405,'METHOD_NOT_ALLOWED')
        result=store.mutate(identity.principal,project,batch,action,body,asset)
        return (201 if action=='create' else 200),result
