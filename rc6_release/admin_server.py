from __future__ import annotations

import argparse
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qs, urlparse

ADMIN_VERSION = "rc6-admin-v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SECRET_KEY_RE = re.compile(r"(password|passwd|secret|token|cookie|credential|api[_-]?key)", re.I)

ARTIFACT_ENDPOINTS = {
    "requirements": "requirement_analysis",
    "code-analysis": "code_analysis",
    "test-cases": "test_case",
    "executions": "execution_attempt",
    "assertions": "assertion",
    "evidence": "evidence",
    "defects": "defect",
    "coverage": "coverage_observation",
    "reports": "report",
    "test-intents": "test_intent",
    "test-conditions": "test_condition",
}


def _home() -> Path:
    return Path(os.environ.get("PFC_AITEST_HOME", os.getcwd())).resolve()


def _state_root() -> Path:
    return Path(os.environ.get("PFC_AITEST_STATE_DIR", str(_home() / "runtime-state"))).resolve()


def _workspace() -> Path:
    raw = os.environ.get("PFC_WORKSPACE", r"D:\PFC")
    return Path(raw).resolve()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return default


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _events() -> List[dict]:
    path = _state_root() / "r1" / "event-stream.jsonl"
    if not path.is_file():
        return []
    rows: List[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    rows.append({"seq": None, "event_type": "INVALID_JSON", "line": line_no})
                    continue
                if isinstance(raw, dict):
                    rows.append(_redact(raw))
    except OSError:
        return []
    return rows


def _projection(events: Iterable[dict]) -> Dict[str, List[dict]]:
    latest: Dict[str, Dict[str, tuple]] = {}
    for index, event in enumerate(events):
        entity_type = str(event.get("entity_type") or "")
        payload = event.get("payload")
        if not entity_type or not isinstance(payload, dict):
            continue
        entity_id = str(event.get("entity_id") or payload.get("id") or payload.get("tc_id") or event.get("event_id") or index)
        version = event.get("entity_version", 1)
        try:
            version_num = int(version)
        except (TypeError, ValueError):
            version_num = 1
        current = latest.setdefault(entity_type, {}).get(entity_id)
        if current is None or (version_num, index) >= (current[0], current[1]):
            latest[entity_type][entity_id] = (version_num, index, _redact(payload))
    return {
        entity_type: [entry[2] for _, entry in sorted(items.items(), key=lambda pair: pair[0])]
        for entity_type, items in latest.items()
    }


def _missions() -> List[dict]:
    root = _state_root() / "missions"
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*.json")):
        item = _read_json(path, {})
        if isinstance(item, dict):
            rows.append(_redact(item))
    return rows


def _bank_reality() -> List[dict]:
    data = _read_json(_state_root() / "bank-reality.json", {})
    if isinstance(data, list):
        return _redact(data)
    if not isinstance(data, dict):
        return []
    rows: List[dict] = []
    for kind, facts in data.items():
        if isinstance(facts, dict):
            for fact_id, fact in facts.items():
                if isinstance(fact, dict):
                    row = dict(fact)
                    row.setdefault("kind", kind)
                    row.setdefault("fact_id", fact_id)
                else:
                    row = {"kind": kind, "fact_id": fact_id, "value": fact}
                rows.append(_redact(row))
        elif isinstance(facts, list):
            for fact in facts:
                row = dict(fact) if isinstance(fact, dict) else {"value": fact}
                row.setdefault("kind", kind)
                rows.append(_redact(row))
    if not rows:
        rows.append(_redact(data))
    return rows


def _tool_profile() -> List[dict]:
    data = _read_json(_workspace() / ".dsh" / "rc6" / "TOOL_PROFILE.json", {})
    if isinstance(data, dict) and isinstance(data.get("tools"), list):
        return _redact(data["tools"])
    return []


def _runtime_identity() -> dict:
    def text(name: str, default: str) -> str:
        path = _home() / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        return default
    return {
        "admin_version": ADMIN_VERSION,
        "build_id": text("BUILD_ID", "SOURCE_TREE"),
        "source_commit": text("SOURCE_COMMIT", "UNKNOWN"),
        "release_status": text("RELEASE_STATUS", "SOURCE_TREE"),
        "durable_truth": "R1_EVENT_STREAM",
        "read_only_projection": True,
        "legacy_aitest_db_used": False,
        "state_root": str(_state_root()),
        "workspace": str(_workspace()),
    }


def _event_rows(events: List[dict], prefixes: tuple) -> List[dict]:
    found = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type.startswith(prefixes):
            found.append(event)
    return found


def _versions(projection: Dict[str, List[dict]], missions: List[dict]) -> List[dict]:
    releases: Dict[str, dict] = {}
    for mission in missions:
        release_id = mission.get("release_id")
        if release_id:
            releases.setdefault(str(release_id), {"release_id": str(release_id), "mission_count": 0, "artifact_count": 0})["mission_count"] += 1
    for rows in projection.values():
        for row in rows:
            if not isinstance(row, dict):
                continue
            release_id = row.get("release_id") or row.get("version_id")
            if release_id:
                releases.setdefault(str(release_id), {"release_id": str(release_id), "mission_count": 0, "artifact_count": 0})["artifact_count"] += 1
    return [releases[key] for key in sorted(releases, reverse=True)]


def _search_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except (TypeError, ValueError):
        return str(value).lower()


def _filter_rows(rows: List[dict], query: Dict[str, List[str]]) -> List[dict]:
    q = (query.get("q") or [""])[0].strip().lower()
    release_id = (query.get("version") or query.get("release_id") or [""])[0].strip()
    requirement_id = (query.get("requirement") or query.get("requirement_id") or [""])[0].strip()
    layer = (query.get("layer") or [""])[0].strip().upper()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if release_id and str(row.get("release_id") or row.get("version_id") or "") != release_id:
            continue
        if requirement_id and str(row.get("requirement_id") or row.get("sr_id") or row.get("requirement") or "") != requirement_id:
            continue
        if layer and str(row.get("layer") or "").upper() != layer:
            continue
        if q and q not in _search_blob(row):
            continue
        out.append(row)
    return out


def _paginate(rows: List[dict], query: Dict[str, List[str]]) -> dict:
    try:
        page = max(1, int((query.get("page") or ["1"])[0]))
    except ValueError:
        page = 1
    try:
        page_size = min(100, max(1, int((query.get("page_size") or ["20"])[0])))
    except ValueError:
        page_size = 20
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


def _overview() -> dict:
    events = _events()
    projection = _projection(events)
    missions = _missions()
    tools = _tool_profile()
    counts = {entity_type: len(rows) for entity_type, rows in projection.items()}
    tool_summary: Dict[str, int] = {}
    for tool in tools:
        status = str(tool.get("status") or "UNKNOWN")
        tool_summary[status] = tool_summary.get(status, 0) + 1
    return {
        "runtime": _runtime_identity(),
        "counts": counts,
        "event_count": len(events),
        "mission_count": len(missions),
        "missions": missions[-10:],
        "tool_summary": tool_summary,
        "bank_reality_count": len(_bank_reality()),
        "versions": _versions(projection, missions),
    }


def _api(path: str, query: Dict[str, List[str]]) -> dict:
    events = _events()
    projection = _projection(events)
    missions = _missions()
    if path == "health":
        return {"status": "PASS", "service": "RC6_ADMIN", "runtime": _runtime_identity()}
    if path == "overview":
        return _overview()
    if path == "versions":
        return _paginate(_filter_rows(_versions(projection, missions), query), query)
    if path == "missions":
        return _paginate(_filter_rows(missions, query), query)
    if path == "workers":
        rows = _event_rows(events, ("WORKER_", "HANDOFF_", "SUFFICIENCY_", "REPAIR_"))
        return _paginate(_filter_rows(rows, query), query)
    if path == "events":
        return _paginate(_filter_rows(events, query), query)
    if path == "tools":
        return _paginate(_filter_rows(_tool_profile(), query), query)
    if path == "bank-reality":
        return _paginate(_filter_rows(_bank_reality(), query), query)
    artifact_type = ARTIFACT_ENDPOINTS.get(path)
    if artifact_type:
        return _paginate(_filter_rows(list(projection.get(artifact_type, [])), query), query)
    if path == "l1-l7":
        return _paginate(_filter_rows(list(projection.get("test_case", [])), query), query)
    raise KeyError(path)


INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RC6 AI测试数字员工 · 后管</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;color:#172033;background:#f5f7fb}*{box-sizing:border-box}body{margin:0}.layout{display:flex;min-height:100vh}.side{width:220px;background:#111827;color:#fff;padding:18px 12px;position:fixed;inset:0 auto 0 0;overflow:auto}.brand{font-weight:700;font-size:17px;padding:6px 10px 16px}.sub{font-size:12px;color:#9ca3af;padding:0 10px 12px}.nav button{width:100%;border:0;background:transparent;color:#d1d5db;text-align:left;padding:10px;border-radius:7px;cursor:pointer;margin:1px 0}.nav button:hover,.nav button.on{background:#263244;color:#fff}.main{margin-left:220px;width:calc(100% - 220px);padding:22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.top h1{font-size:22px;margin:0}.truth{font-size:12px;color:#4b5563}.filters{display:flex;gap:8px;flex-wrap:wrap;background:#fff;padding:12px;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:12px}.filters input,.filters select{padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;min-width:150px}.filters button{border:0;background:#1f2937;color:#fff;padding:8px 14px;border-radius:6px;cursor:pointer}.cards{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:10px;margin-bottom:12px}.card{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:14px}.card b{font-size:24px;display:block;margin-top:4px}.panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}.panelhead{padding:12px 14px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}.tablewrap{overflow:auto;max-height:68vh}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px 10px;border-bottom:1px solid #eef0f3;text-align:left;vertical-align:top;white-space:nowrap}th{background:#fafafa;position:sticky;top:0;z-index:1}td.long{white-space:normal;min-width:260px;max-width:520px}.badge{display:inline-block;padding:2px 7px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:11px}.pager{display:flex;gap:8px;align-items:center;padding:10px 14px}.pager button{padding:5px 10px}.empty{padding:40px;text-align:center;color:#6b7280}.error{padding:12px;background:#fff1f2;color:#9f1239;border-radius:8px;margin-bottom:10px}@media(max-width:900px){.side{width:170px}.main{margin-left:170px;width:calc(100% - 170px)}.cards{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="layout"><aside class="side"><div class="brand">RC6 测试后管</div><div class="sub">R1 Event Stream 只读投影</div><div class="nav" id="nav"></div></aside><main class="main"><div class="top"><h1 id="title">总览</h1><div class="truth" id="truth">正在连接 RC6…</div></div><div id="err"></div><div class="filters"><input id="q" placeholder="搜索"><input id="version" placeholder="版本，如 BLOAN-PF1.2.0"><input id="req" placeholder="需求编号"><select id="layer"><option value="">全部层级</option><option>L1</option><option>L2</option><option>L3</option><option>L4</option><option>L5</option><option>L6</option><option>L7</option></select><button id="search">查询</button></div><div id="content"></div></main></div>
<script>
const menus=[['overview','总览'],['versions','版本管理'],['requirements','需求分析'],['code-analysis','代码分析'],['test-cases','测试用例'],['l1-l7','L1-L7 测试设计'],['executions','测试执行 / Attempt'],['evidence','证据'],['defects','缺陷'],['coverage','覆盖率'],['reports','测试报告'],['missions','Mission'],['workers','Worker / Session'],['tools','工具状态'],['bank-reality','Bank Reality'],['events','R1 事件流']];let current='overview',page=1;
const nav=document.getElementById('nav');menus.forEach(([id,name])=>{const b=document.createElement('button');b.textContent=name;b.dataset.id=id;b.onclick=()=>{current=id;page=1;render()};nav.appendChild(b)});document.getElementById('search').onclick=()=>{page=1;render()};
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function simple(v){if(v===null||v===undefined)return '';if(typeof v==='object')return JSON.stringify(v);return String(v)}
function params(){const p=new URLSearchParams({page:String(page),page_size:'20'});let v=document.getElementById('q').value.trim();if(v)p.set('q',v);v=document.getElementById('version').value.trim();if(v)p.set('version',v);v=document.getElementById('req').value.trim();if(v)p.set('requirement',v);v=document.getElementById('layer').value;if(v)p.set('layer',v);return p}
async function get(path){const r=await fetch('/api/'+path+'?'+params());if(!r.ok)throw new Error(await r.text());return r.json()}
function table(data){const rows=data.items||[];if(!rows.length)return '<div class="panel"><div class="empty">当前 R1 Truth 中没有符合条件的数据</div></div>';const keys=[];rows.forEach(r=>Object.keys(r||{}).forEach(k=>{if(!keys.includes(k)&&keys.length<10)keys.push(k)}));let h='<div class="panel"><div class="tablewrap"><table><thead><tr>'+keys.map(k=>'<th>'+esc(k)+'</th>').join('')+'</tr></thead><tbody>';rows.forEach(r=>{h+='<tr>'+keys.map(k=>'<td class="'+(typeof r[k]==='object'?'long':'')+'">'+esc(simple(r[k]))+'</td>').join('')+'</tr>'});h+='</tbody></table></div><div class="pager"><button id="prev">上一页</button><span>第 '+data.page+' / '+(data.pages||1)+' 页，共 '+data.total+' 条</span><button id="next">下一页</button></div></div>';return h}
function overview(d){const c=d.counts||{}, cards=[['R1事件',d.event_count||0],['Mission',d.mission_count||0],['测试用例',c.test_case||0],['执行Attempt',c.execution_attempt||0],['缺陷',c.defect||0],['证据',c.evidence||0],['需求分析',c.requirement_analysis||0],['代码分析',c.code_analysis||0]];return '<div class="cards">'+cards.map(x=>'<div class="card">'+esc(x[0])+'<b>'+esc(x[1])+'</b></div>').join('')+'</div><div class="panel"><div class="panelhead"><b>运行状态</b><span class="badge">'+esc(d.runtime?.release_status||'')+'</span></div><div style="padding:14px;line-height:1.9">SOURCE_COMMIT：'+esc(d.runtime?.source_commit||'')+'<br>R1 Truth：'+esc(d.runtime?.durable_truth||'')+'<br>Bank Reality：'+esc(d.bank_reality_count||0)+' 条<br>工具状态：'+esc(JSON.stringify(d.tool_summary||{}))+'</div></div>'}
async function render(){document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('on',b.dataset.id===current));document.getElementById('title').textContent=(menus.find(x=>x[0]===current)||[])[1]||current;document.getElementById('err').innerHTML='';try{const d=await get(current);document.getElementById('content').innerHTML=current==='overview'?overview(d):table(d);document.getElementById('truth').textContent='R1 Event Stream · 实时只读';const prev=document.getElementById('prev'),next=document.getElementById('next');if(prev)prev.onclick=()=>{if(page>1){page--;render()}};if(next)next.onclick=()=>{if(page<(d.pages||1)){page++;render()}}}catch(e){document.getElementById('err').innerHTML='<div class="error">加载失败：'+esc(e.message)+'</div>'}}
render();setInterval(()=>{if(current==='overview')render()},10000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "RC6Admin/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        syslog = os.environ.get("PFC_ADMIN_ACCESS_LOG", "0") == "1"
        if syslog:
            super().log_message(fmt, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(_redact(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/"):
            name = parsed.path[len("/api/"):].strip("/")
            try:
                self._send_json(_api(name, parse_qs(parsed.query, keep_blank_values=False)))
            except KeyError:
                self._send_json({"error": "NOT_FOUND", "path": name}, 404)
            except Exception as exc:
                self._send_json({"error": "ADMIN_PROJECTION_FAILED", "type": type(exc).__name__, "message": str(exc)}, 500)
            return
        self._send_json({"error": "NOT_FOUND"}, 404)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.admin_server")
    parser.add_argument("--host", default=os.environ.get("PFC_ADMIN_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PFC_ADMIN_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("PFC_ADMIN_ALLOW_REMOTE") != "1":
        raise SystemExit("ADMIN_REMOTE_BIND_FORBIDDEN")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("RC6_ADMIN_READY=http://%s:%d" % (args.host, args.port), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
