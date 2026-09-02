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
    emit({"ok":False,"status":"DENIED_BY_DEFAULT","reason":"DB writes require project-specific adapter, H3 and explicit human approval"})
if __name__=='__main__': main()
