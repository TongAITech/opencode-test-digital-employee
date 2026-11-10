"""M1 HTTP boundary; the injected store still owns all business decisions.

No store adapter is enabled by default. Host proof and the original subject's
write context are independent of the pure request codec and database receipt.
"""
import re
from urllib.parse import unquote, urlsplit

from .business_store import BusinessError, BusinessStore
from .write_context import require_write_context


def metadata_request(handler, identity, connection_factory, context_key,
                     metadata_store_factory=None):
    url = urlsplit(handler.path)
    match = re.fullmatch(r'/api/workbench/v1/projects/([^/]+)/metadata', url.path)
    if match is None:
        raise BusinessError(404, 'RESOURCE_NOT_FOUND')
    if handler.command not in ('GET', 'PATCH'):
        raise BusinessError(405, 'METHOD_NOT_ALLOWED')
    try:
        project = unquote(match[1], errors='strict')
        project.encode('utf-8', 'strict')
    except UnicodeError:
        raise BusinessError(400, 'INVALID_METADATA_TARGET')
    if not project or '/' in project or '\x00' in project:
        raise BusinessError(400, 'INVALID_METADATA_TARGET')
    writing = handler.command == 'PATCH'
    if writing:
        if identity.mutation_authorized is not True:
            raise BusinessError(403, 'MUTATION_AUTH_REQUIRED')
        require_write_context(handler.headers, context_key, identity.principal)
    if metadata_store_factory is None:
        raise BusinessError(503, 'METADATA_ADAPTER_UNAVAILABLE')
    with connection_factory() as connection:
        # Permission precedes body/query parsing. The actual store must check
        # current authorization again inside its own atomic rename transaction.
        with BusinessStore(connection)._scope(identity.principal, project, writing):
            pass
        if url.query:
            raise BusinessError(400, 'INVALID_METADATA_QUERY')
        store = metadata_store_factory(connection)
        if not writing:
            return 200, store.get_metadata(identity.principal, project)
        from .project_metadata_codec import (MAX_BODY_BYTES, MetadataProtocolError,
                                             parse_rename_request)
        lengths = handler.headers.get_all('Content-Length', [])
        content_types = handler.headers.get_all('Content-Type', [])
        if (handler.headers.get_all('Transfer-Encoding', []) or
                len(lengths) != 1 or len(content_types) != 1 or
                not re.fullmatch(r'[1-9][0-9]{0,5}', lengths[0]) or
                int(lengths[0]) > MAX_BODY_BYTES or
                handler.headers.get_content_type() != 'application/json'):
            raise BusinessError(400, 'INVALID_METADATA_BODY')
        charset = handler.headers.get_content_charset()
        if charset is not None and charset.lower() not in ('utf-8', 'utf8'):
            raise BusinessError(400, 'INVALID_METADATA_BODY')
        length = int(lengths[0])
        handler.connection.settimeout(5)
        try:
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise BusinessError(400, 'INCOMPLETE_METADATA_BODY')
            request = parse_rename_request(raw, project)
        except MetadataProtocolError as error:
            raise BusinessError(400, error.code) from error
        except (TimeoutError, ConnectionResetError, ConnectionAbortedError):
            handler.close_connection = True
            raise BusinessError(400, 'INCOMPLETE_METADATA_BODY')
        return 200, store.rename(identity.principal, request)
