"""Strict typed draft content. Text is never an execution-result oracle."""
import json
from .business_store import BusinessError

SCHEMAS={
 'milestone':({'due_date':'text','description':'text','owner_display':'text'},{'due_date'}),
 'case_draft':({'preconditions':'list','steps':'list','expected_results':'list','oracle_notes':'text'},{'steps','expected_results'}),
 'obligation_draft':({'business_rule':'text','scenario':'text','oracle_notes':'text'},{'business_rule','scenario'}),
 'defect_note':({'reproduction_notes':'text','expected_notes':'text','actual_notes':'text'},{'reproduction_notes','expected_notes','actual_notes'}),
 'report_draft':({'body':'text','tags':'tags'},{'body'}),
 'knowledge':({'body':'text','tags':'tags'},{'body'}),
 'meeting_minutes':({'body':'text','tags':'tags'},{'body'}),
}


def validate_payload(kind,payload,date_parser):
    if kind not in SCHEMAS:raise BusinessError(400,'UNSUPPORTED_ASSET_KIND')
    fields,required=SCHEMAS[kind]
    if not isinstance(payload,dict) or set(payload)-set(fields) or not required.issubset(payload):raise BusinessError(400,'INVALID_PAYLOAD')
    for key,value in payload.items():
        shape=fields[key]
        if shape=='text':
            limit=256 if key=='owner_display' else 8192
            if not isinstance(value,str) or '\x00' in value or len(value)>limit or (key in required and not value.strip()):raise BusinessError(400,'INVALID_PAYLOAD')
        else:
            limit,count=(128,30) if shape=='tags' else (8192,100)
            if not isinstance(value,list) or len(value)>count or (key in required and not value):raise BusinessError(400,'INVALID_PAYLOAD')
            if any(not isinstance(item,str) or not item.strip() or '\x00' in item or len(item)>limit for item in value):raise BusinessError(400,'INVALID_PAYLOAD')
    try:size=len(json.dumps(payload,ensure_ascii=False).encode())
    except UnicodeError:raise BusinessError(400,'INVALID_PAYLOAD')
    if size>49152:raise BusinessError(400,'INVALID_PAYLOAD')
    if kind=='milestone':date_parser(payload['due_date'])
