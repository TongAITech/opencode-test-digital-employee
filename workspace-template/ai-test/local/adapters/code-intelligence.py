from __future__ import annotations
import argparse, json
from pathlib import Path

def load_request():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True); a=p.parse_args()
    return json.loads(Path(a.request).read_text(encoding='utf-8'))

def emit(value):
    print(json.dumps(value,ensure_ascii=False))

import subprocess

def run(args,cwd=None):
    cp=subprocess.run(args,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,check=False)
    return {"ok":cp.returncode==0,"returncode":cp.returncode,"stdout":cp.stdout,"stderr":cp.stderr}

def main():
    req=load_request(); repo=req.get("repository_path")
    if not repo or not Path(repo).exists(): return emit({"ok":False,"status":"REPOSITORY_REQUIRED"})
    change_range=req.get("range") or req.get("commit_range") or "HEAD~1..HEAD"
    diff=run(["git","-C",repo,"diff","--name-status",change_range])
    names=[]
    for line in diff.get("stdout","").splitlines():
        parts=line.split("\t")
        if parts: names.append(parts[-1])
    candidates=[]
    for name in names[:200]:
        p=Path(repo)/name
        if p.exists() and p.is_file():
            text=p.read_text(encoding="utf-8",errors="replace")[:200000]
            signals=[]
            for token in ("Controller","Service","Repository","Mapper","@RequestMapping","@PostMapping","@GetMapping","Kafka","Rabbit","SELECT ","INSERT ","UPDATE "):
                if token in text: signals.append(token)
            candidates.append({"path":name,"signals":signals})
    emit({"ok":diff["ok"],"status":"NATIVE_CODE_INTELLIGENCE","range":change_range,"changed_files":names,"candidates":candidates,"provider":"native-fallback"})
if __name__=='__main__': main()
