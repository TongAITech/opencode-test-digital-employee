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
    if req.get("mock_rows") is not None:
        return emit({"ok":True,"status":"QUERY_OK","rows":req.get("mock_rows"),"count":len(req.get("mock_rows") or [])})
    emit({"ok":False,"status":"NOT_CONFIGURED","required":"bind approved read-only DB adapter; credentials must stay behind secret_ref"})
if __name__=='__main__': main()
