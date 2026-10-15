from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rc7_release.final_unified_overlay import REQUIRED_DSH_PACKAGES, npm_package_path


def find_one(root: Path, name: str) -> Optional[Path]:
    matches = list(root.rglob(name)) if root.exists() else []
    return matches[0] if matches else None


def run(cmd: Sequence[str], env: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None, timeout: int = 45) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
        return proc.returncode == 0, proc.stdout[-6000:]
    except Exception as exc:
        return False, "%s:%s" % (type(exc).__name__, exc)


def tool_result(path: Optional[Path], probe: Optional[Sequence[str]] = None, env: Optional[Dict[str, str]] = None, timeout: int = 45) -> Dict[str, object]:
    if path is None or not path.is_file():
        return {"status": "FAIL", "reason": "MISSING", "path": str(path) if path else None}
    result: Dict[str, object] = {"status": "PASS", "path": str(path)}
    if probe:
        ok, out = run(probe, env=env, timeout=timeout)
        result["status"] = "PASS" if ok else "FAIL"
        result["probe_tail"] = out
    return result


def maven_offline_smoke(root: Path, java_home: Path, maven: Path, repo: Path) -> Dict[str, object]:
    if not maven.is_file() or not repo.is_dir() or not (java_home / "bin" / "javac.exe").is_file():
        return {"status": "FAIL", "reason": "MAVEN_JDK_OR_REPO_MISSING"}
    with tempfile.TemporaryDirectory(prefix="rc7-mvn-") as td:
        project = Path(td)
        test_dir = project / "src" / "test" / "java" / "rc7"
        test_dir.mkdir(parents=True)
        (project / "pom.xml").write_text("""<project xmlns=\"http://maven.apache.org/POM/4.0.0\"><modelVersion>4.0.0</modelVersion><groupId>rc7</groupId><artifactId>offline-smoke</artifactId><version>1</version><properties><maven.compiler.source>8</maven.compiler.source><maven.compiler.target>8</maven.compiler.target></properties><dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.11.4</version><scope>test</scope></dependency></dependencies><build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.5.2</version></plugin></plugins></build></project>""", encoding="utf-8")
        (test_dir / "OfflineSmokeTest.java").write_text("""package rc7; import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; class OfflineSmokeTest { @Test void works(){ assertEquals(4, 2+2); } }""", encoding="utf-8")
        env = dict(os.environ)
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + str(maven.parent) + os.pathsep + env.get("PATH", "")
        ok, out = run([str(maven), "-o", "-q", "-Dmaven.repo.local=%s" % repo, "test"], env=env, cwd=project, timeout=90)
        reports = list(project.glob("target/surefire-reports/TEST-*.xml"))
        return {"status": "PASS" if ok and reports else "FAIL", "junit_xml": bool(reports), "probe_tail": out}


def playwright_smoke(node: Path, modules: Path, chrome: Path) -> Dict[str, object]:
    if not node.is_file() or not (modules / "playwright" / "package.json").is_file() or not chrome.is_file():
        return {"status": "FAIL", "reason": "NODE_PLAYWRIGHT_OR_CHROME_MISSING"}
    env = dict(os.environ)
    env["NODE_PATH"] = str(modules)
    script = "const { chromium }=require('playwright'); (async()=>{const b=await chromium.launch({headless:true,executablePath:process.argv[1]});const p=await b.newPage();await p.setContent('<button aria-label=\\\"submit\\\">OK</button>');const t=await p.getByRole('button').innerText();console.log(t);await b.close();if(t!=='OK')process.exit(2)})().catch(e=>{console.error(e);process.exit(1)})"
    ok, out = run([str(node), "-e", script, str(chrome)], env=env, timeout=60)
    return {"status": "PASS" if ok else "FAIL", "probe_tail": out}


def qualify(home: Path) -> Dict[str, object]:
    rt = home / "workspace-template" / "runtime"
    py = rt / "python" / "python.exe"
    node = rt / "node" / "node.exe"
    java = rt / "java" / "bin" / "java.exe"
    javac = rt / "java" / "bin" / "javac.exe"
    maven = rt / "maven" / "bin" / "mvn.cmd"
    m2 = rt / "maven-repository"
    chrome = rt / "browser" / "chrome-win64" / "chrome.exe"
    bsk = find_one(rt / "browser" / "browserskill", "bsk.exe")
    rg = find_one(rt / "ripgrep", "rg.exe")
    k6 = find_one(rt / "k6", "k6.exe")
    zap = find_one(rt / "zap", "zap.bat")
    allure = find_one(rt / "allure", "allure.bat")
    codegraph = rt / "code-intelligence" / "codegraph" / "codegraph-server-win32-x64.exe"
    exec_modules = rt / "node-execution" / "node_modules"
    gitnexus = find_one(rt / "node-execution" / "node_modules" / ".bin", "gitnexus.cmd")
    vendor = rt / "dsh-plugins"

    tools: Dict[str, Dict[str, object]] = {}
    tools["python"] = tool_result(py, [str(py), "--version"] if py.is_file() else None)
    tools["pytest"] = tool_result(py, [str(py), "-m", "pytest", "--version"] if py.is_file() else None)
    tools["node"] = tool_result(node, [str(node), "--version"] if node.is_file() else None)
    tools["java"] = tool_result(java, [str(java), "-version"] if java.is_file() else None)
    tools["javac"] = tool_result(javac, [str(javac), "-version"] if javac.is_file() else None)
    java_env = dict(os.environ)
    java_env["JAVA_HOME"] = str(rt / "java")
    java_env["PATH"] = str(rt / "java" / "bin") + os.pathsep + os.environ.get("PATH", "")
    tools["maven"] = tool_result(maven, [str(maven), "--version"] if maven.is_file() else None, env=java_env)
    tools["codegraph"] = tool_result(codegraph, [str(codegraph), "--help"] if codegraph.is_file() else None)
    tools["chrome"] = tool_result(chrome)
    tools["browserskill"] = tool_result(bsk, [str(bsk), "--version"] if bsk else None)
    tools["ripgrep"] = tool_result(rg, [str(rg), "--version"] if rg else None)
    tools["k6"] = tool_result(k6, [str(k6), "version"] if k6 else None)
    tools["allure"] = tool_result(allure, [str(allure), "--version"] if allure else None, env=java_env)
    tools["zap"] = tool_result(zap)
    tools["gitnexus"] = tool_result(gitnexus, [str(gitnexus), "--version"] if gitnexus else None)

    python_import = {"status": "FAIL"}
    if py.is_file():
        ok, out = run([str(py), "-c", "import docx,openpyxl,pptx,pypdf,cv2,onnxruntime,rapidocr_onnxruntime; print('PYTHON_PROVIDERS_OK')"], timeout=60)
        python_import = {"status": "PASS" if ok else "FAIL", "probe_tail": out}

    plugins = {}
    for name in REQUIRED_DSH_PACKAGES:
        path = npm_package_path(vendor, name) / "package.json"
        plugins[name] = {"status": "PASS" if path.is_file() else "FAIL", "path": str(path)}

    l1 = maven_offline_smoke(home, rt / "java", maven, m2)
    l4 = playwright_smoke(node, exec_modules, chrome)
    layer_skills = {}
    for level in range(1, 8):
        design = home / ".dsh" / "skills" / ("pfc-l%d-test-design" % level) / "SKILL.md"
        execution = home / ".dsh" / "skills" / ("pfc-l%d-test-execution" % level) / "SKILL.md"
        layer_skills["L%d" % level] = {"status": "PASS" if design.is_file() and execution.is_file() else "FAIL", "design": design.is_file(), "execution": execution.is_file()}

    required_tool_names = ["python", "pytest", "node", "java", "javac", "maven", "codegraph", "chrome", "browserskill", "ripgrep", "k6", "allure", "zap"]
    tools_pass = all(tools[name]["status"] == "PASS" for name in required_tool_names)
    plugin_pass = all(v["status"] == "PASS" for v in plugins.values())
    layers_pass = all(v["status"] == "PASS" for v in layer_skills.values())
    gates = {
        "CORE_RUNTIME_PASS": "PASS" if tools_pass else "FAIL",
        "DSH_PLUGIN_PAYLOAD_PASS": "PASS" if plugin_pass else "FAIL",
        "LOCAL_VISION_DOCUMENT_PASS": python_import["status"],
        "L1_JUNIT_MAVEN_OFFLINE_PASS": l1["status"],
        "L4_PLAYWRIGHT_BROWSER_PASS": l4["status"],
        "L1_L7_WORKER_CATALOG_PASS": "PASS" if layers_pass else "FAIL",
        "BANK_BINDINGS": "HOLD_FIELD_CONFIGURATION_REQUIRED",
        "REAL_BANK_MISSION": "HOLD_FIELD_EVIDENCE_REQUIRED",
    }
    engineering_pass = all(value == "PASS" for key, value in gates.items() if key not in ("BANK_BINDINGS", "REAL_BANK_MISSION"))
    return {
        "schema_version": "pfc.aitest.rc7.final-unified-qualification.v1",
        "status": "PASS" if engineering_pass else "FAIL",
        "engineering_gate": "UNIFIED_ENGINEERING_PASS" if engineering_pass else "UNIFIED_ENGINEERING_FAIL",
        "durable_truth": "R1_EVENT_STREAM",
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "tools": tools,
        "python_providers": python_import,
        "dsh_plugins": plugins,
        "maven_offline_smoke": l1,
        "playwright_smoke": l4,
        "layer_workers": layer_skills,
        "gates": gates,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--home", required=True)
    p.add_argument("--output")
    p.add_argument("--require-pass", action="store_true")
    args = p.parse_args(argv)
    result = qualify(Path(args.home).resolve())
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
