from __future__ import annotations
import argparse, json
from pathlib import Path

def load_request():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True); a=p.parse_args()
    return json.loads(Path(a.request).read_text(encoding='utf-8'))

def emit(value):
    print(json.dumps(value,ensure_ascii=False))

def main():
    req=load_request(); path=req.get("file_path") or req.get("export_path")
    if not path: return emit({"ok":False,"status":"NOT_CONFIGURED","required":"file_path or bind an approved submission platform adapter"})
    p=Path(path)
    if not p.exists(): return emit({"ok":False,"status":"SOURCE_NOT_FOUND","path":str(p)})
    emit({"ok":True,"status":"SUBMISSION_FOUND","payload":json.loads(p.read_text(encoding="utf-8")),"source_ref":str(p)})
if __name__=='__main__': main()
