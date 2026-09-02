from __future__ import annotations
import argparse, json
from pathlib import Path

def load_request():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True); a=p.parse_args()
    return json.loads(Path(a.request).read_text(encoding='utf-8'))

def emit(value):
    print(json.dumps(value,ensure_ascii=False))

def main():
    req=load_request()
    if req.get("mock_logs") is not None:
        return emit({"ok":True,"status":"CAT_EVIDENCE_COLLECTED","logs":req.get("mock_logs"),"trace_id":req.get("trace_id"),"business_key":req.get("business_key")})
    path=req.get("file_path")
    if path and Path(path).exists():
        text=Path(path).read_text(encoding="utf-8",errors="replace")
        keys=[str(x) for x in [req.get("trace_id"),req.get("request_id"),req.get("business_key")] if x]
        lines=[line for line in text.splitlines() if not keys or any(k in line for k in keys)]
        return emit({"ok":True,"status":"CAT_EVIDENCE_COLLECTED","logs":lines[-500:],"source_ref":path})
    emit({"ok":False,"status":"NOT_CONFIGURED","required":"mock_logs/file_path or approved CAT query implementation"})
if __name__=='__main__': main()
