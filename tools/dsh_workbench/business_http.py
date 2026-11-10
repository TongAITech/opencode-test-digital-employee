"""B06 real HTTP adapter. Trusted Host identity provider is injected server-side.

No body/query/header principal fallback exists. Missing Host integration fails
closed. The adapter neither writes R1 nor invokes an unscoped legacy API.
"""
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import re
from urllib.parse import parse_qs,unquote,urlsplit
from .business_scope import ScopeStore
from .business_store import BusinessError
from .write_context import SCHEMA,subject_write_context

@dataclass(frozen=True)
class HostIdentity:
    principal: str
    mutation_authorized: bool = False


def scope_handler(connection_factory,cursor_key,host_identity_provider=None,quality_service_factory=None,metadata_store_factory=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass

        def respond(self,status,value):
            data=json.dumps(value,ensure_ascii=False).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # A disconnected peer cannot receive an error response either.
                # Do not re-enter the business-error path or retry a committed
                # mutation merely because its receipt could not be delivered.
                self.close_connection = True

        def do_GET(self):
            try:
                if host_identity_provider is None:
                    raise BusinessError(503,'HOST_IDENTITY_UNAVAILABLE')
                identity=host_identity_provider(self)
                if not isinstance(identity,HostIdentity) or not isinstance(identity.principal,str) or not identity.principal.strip():
                    raise BusinessError(403,'FORBIDDEN')
                if len(self.path)>16384:raise BusinessError(400,'INVALID_SCOPE')
                url=urlsplit(self.path)
                directory=re.fullmatch(r'/api/workbench/v1/projects(?:/([^/]+)/release-dates)?',url.path)
                if directory:
                    from .business_directory import DirectoryStore
                    try:q=parse_qs(url.query,keep_blank_values=True,max_num_fields=4,strict_parsing=True) if url.query else {}
                    except ValueError:raise BusinessError(400,'INVALID_DIRECTORY_QUERY')
                    if set(q)-{'page_size','page_cursor'} or any(len(v)!=1 for v in q.values()):raise BusinessError(400,'INVALID_DIRECTORY_QUERY')
                    try:size=int(q.get('page_size',['100'])[0])
                    except ValueError:raise BusinessError(400,'INVALID_PAGE_SIZE')
                    project=unquote(directory[1]) if directory[1] else None
                    if project is not None and (not project or '/' in project):raise BusinessError(400,'INVALID_DIRECTORY_QUERY')
                    with connection_factory() as connection:value=DirectoryStore(connection,cursor_key).directory(identity.principal,project,size,q.get('page_cursor',[None])[0])
                    self.respond(200,value)
                    return
                if url.path=='/api/workbench/v1/write-context':
                    if url.query:raise BusinessError(400,'INVALID_WRITE_CONTEXT_REQUEST')
                    self.respond(200,{'schema':SCHEMA,'write_context':subject_write_context(cursor_key,identity.principal)})
                    return
                if re.fullmatch(r'/api/workbench/v1/projects/([^/]+)/metadata',url.path):
                    from .project_metadata_http import metadata_request
                    status,value=metadata_request(self,identity,connection_factory,cursor_key,metadata_store_factory)
                    self.respond(status,value)
                    return
                if '/batches/' in url.path:
                    from .business_asset_http import asset_request
                    status,value=asset_request(self,identity,connection_factory,cursor_key)
                    self.respond(status,value)
                    return
                graph_match=re.fullmatch(r'/api/workbench/v1/missions/([^/]+)/(graph|workitems)',url.path)
                if graph_match:
                    try:q=parse_qs(url.query,keep_blank_values=True,strict_parsing=True,max_num_fields=4)
                    except ValueError:raise BusinessError(400,'INVALID_SCOPE')
                    if set(q)!={'project_id','batch_id','release_date'} or any(len(v)!=1 or not v[0] for v in q.values()):raise BusinessError(400,'INVALID_SCOPE')
                    if quality_service_factory is None:raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE')
                    with connection_factory() as connection:
                        service=quality_service_factory(ScopeStore(connection,cursor_key))
                        if not callable(getattr(service,'graph',None)):raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE')
                        value=service.graph(identity.principal,q['project_id'][0],q['batch_id'][0],q['release_date'][0],unquote(graph_match[1]),graph_match[2])
                    self.respond(200,value)
                    return
                match=re.fullmatch(r'/api/workbench/v1/projects/([^/]+)/release-dates/(\d{4}-\d{2}-\d{2})/(scope|quality)',url.path)
                if match is None:raise BusinessError(404,'RESOURCE_NOT_FOUND')
                project=unquote(match[1])
                if not project or '/' in project:raise BusinessError(400,'INVALID_SCOPE')
                try:q=parse_qs(url.query,keep_blank_values=True,max_num_fields=400,strict_parsing=True) if url.query else {}
                except ValueError:raise BusinessError(400,'INVALID_SCOPE')
                quality=match[3]=='quality'
                allowed={'batch_id','requirement_ids','system_version_ids','sst_ids','page_size','page_cursor'}
                if quality:allowed={'batch_id','mission_id','page_size'}
                if set(q)-allowed or any(len(q[k])!=1 for k in ('batch_id','page_size','page_cursor') if k in q):
                    raise BusinessError(400,'INVALID_SCOPE')
                try:page_size=int(q.get('page_size',['100'])[0])
                except ValueError:raise BusinessError(400,'INVALID_PAGE_SIZE')
                # The connection belongs to this request; identity cannot leak to
                # another request or be supplied by the browser's query/body.
                with connection_factory() as connection:
                    if quality:
                        if quality_service_factory is None:raise BusinessError(503,'TRUTH_SOURCE_UNAVAILABLE')
                        if any(len(q.get(k,[]))!=1 or not q[k][0] for k in ('batch_id','mission_id')):raise BusinessError(400,'INVALID_SCOPE')
                        value=quality_service_factory(ScopeStore(connection,cursor_key)).quality(identity.principal,project,q['batch_id'][0],match[2],q['mission_id'][0],page_size)
                    else:value=ScopeStore(connection,cursor_key).scope(identity.principal,project,batch_id=q.get('batch_id',[None])[0],release_date=match[2],requirement_ids=q.get('requirement_ids'),system_version_ids=q.get('system_version_ids'),sst_ids=q.get('sst_ids'),page_size=page_size,page_cursor=q.get('page_cursor',[None])[0])
                self.respond(200,value)
            except BusinessError as error:
                self.respond(error.status,{'error':{'code':error.code}})
            except Exception:
                # Do not leak database, credential or resource-existence details.
                self.respond(503,{'error':{'code':'SCOPE_SOURCE_UNAVAILABLE'}})

        def asset_mutation(self):
            metadata=bool(re.fullmatch(r'/api/workbench/v1/projects/([^/]+)/metadata',urlsplit(self.path).path))
            if not metadata and '/batches/' not in urlsplit(self.path).path:
                self.respond(405,{'error':{'code':'METHOD_NOT_ALLOWED'}})
                return
            try:
                if host_identity_provider is None:raise BusinessError(503,'HOST_IDENTITY_UNAVAILABLE')
                identity=host_identity_provider(self)
                if not isinstance(identity,HostIdentity) or not isinstance(identity.principal,str) or not identity.principal.strip():raise BusinessError(403,'FORBIDDEN')
                if len(self.path)>16384:raise BusinessError(400,'INVALID_ASSET_REQUEST')
                if metadata:
                    from .project_metadata_http import metadata_request
                    status,value=metadata_request(self,identity,connection_factory,cursor_key,metadata_store_factory)
                else:
                    from .business_asset_http import asset_request
                    status,value=asset_request(self,identity,connection_factory,cursor_key)
                self.respond(status,value)
            except BusinessError as error:self.respond(error.status,{'error':{'code':error.code}})
            except Exception:self.respond(503,{'error':{'code':'METADATA_SOURCE_UNAVAILABLE' if metadata else 'ASSET_SOURCE_UNAVAILABLE'}})
        do_POST=asset_mutation
        do_PATCH=asset_mutation
        do_DELETE=asset_mutation
        def do_PUT(self):self.respond(405,{'error':{'code':'METHOD_NOT_ALLOWED'}})
    return Handler


def create_scope_server(address,connection_factory,cursor_key,host_identity_provider=None,quality_service_factory=None,metadata_store_factory=None):
    return ThreadingHTTPServer(address,scope_handler(connection_factory,cursor_key,host_identity_provider,quality_service_factory,metadata_store_factory))
