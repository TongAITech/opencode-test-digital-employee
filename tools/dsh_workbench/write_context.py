"""Opaque subject-domain fence for pending writes; never an authorization token."""
import hashlib
import hmac
import json
from .business_store import BusinessError

SCHEMA='dsh-workbench/write-context/v1'


def subject_write_context(key,principal):
    if not isinstance(key,bytes) or len(key)<32:raise BusinessError(503,'WRITE_CONTEXT_UNAVAILABLE')
    if not isinstance(principal,str) or not principal.strip():raise BusinessError(403,'FORBIDDEN')
    try:body=SCHEMA.encode()+b'\x00'+json.dumps({'principal':principal},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    except UnicodeError:raise BusinessError(503,'WRITE_CONTEXT_UNAVAILABLE')
    return 'wctx1.'+hmac.new(key,body,hashlib.sha256).hexdigest()


def require_write_context(headers,key,principal):
    expected=subject_write_context(key,principal)
    supplied=headers.get('X-DSH-Write-Context')
    if not supplied:raise BusinessError(403,'WRITE_CONTEXT_REQUIRED')
    try:valid=isinstance(supplied,str) and hmac.compare_digest(supplied,expected)
    except TypeError:valid=False
    if not valid:raise BusinessError(409,'WRITE_CONTEXT_CHANGED')
