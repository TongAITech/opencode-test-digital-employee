from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

FROZEN_G1_G4_RUNNER_PATH = "tools/run_wave2_validation.py"
FROZEN_G1_G4_RUNNER_BLOB = "b006cecb48673a5b8735dda9e1b645ebafe7f1fc"

SUITES = (
    "test_g5_product_path.py",
    "test_g5_worker_binding_and_recovery.py",
    "test_g5_adversarial_defect_truth.py",
    "test_g5_human_gate_and_duplicate_correlation.py",
    "test_g5_same_mission_e2e.py",
    "test_g5_opencode_surface.py",
)
RUNTIME_ORACLE_SUITES = {
    "test_g5_adversarial_defect_truth.py",
    "test_g5_human_gate_and_duplicate_correlation.py",
    "test_g5_same_mission_e2e.py",
}


def git_blob_sha(path: Path) -> str | None:
    if not path.is_file(): return None
    body=path.read_bytes(); return hashlib.sha1(f"blob {len(body)}\0".encode("utf-8")+body).hexdigest()


def parse_last_json(text: str) -> dict[str, Any] | None:
    decoder=json.JSONDecoder(); values=[]
    for index,char in enumerate(text):
        if char!="{": continue
        try: value,end=decoder.raw_decode(text[index:])
        except json.JSONDecodeError: continue
        if isinstance(value,dict) and not text[index+end:].strip(): values.append(value)
    return values[-1] if values else None


def product_runtime_green(parsed: dict[str, Any]) -> bool:
    checks=parsed.get("runtime_behavior_checks") or parsed.get("contract_checks") or {}
    required={"g5_command_callable","g5_cli_registered","director_status_is_r1_truth","cli_status_is_json_r1_truth","invalid_role_fails_with_g5_role_forbidden","invalid_action_fails_closed"}
    return isinstance(checks,dict) and all(checks.get(k) is True for k in required)


def worker_runtime_green(parsed: dict[str, Any]) -> bool:
    checks=parsed.get("runtime_behavior_checks") or parsed.get("contract_checks") or {}
    required={"defect_hunter_task_dispatches","current_binding_accepted","wrong_task_rejected","wrong_attempt_rejected","wrong_session_rejected","stale_predecessor_rejected_after_rotation","successor_binding_accepted_after_rotation","root_logical_agent_binding_survives_rotation","restart_work_context_uses_durable_truth"}
    return isinstance(checks,dict) and all(checks.get(k) is True for k in required)


def opencode_runtime_green(root: Path, parsed: dict[str, Any]) -> bool:
    # Static TypeScript/agent assertions remain in the suite, but GREEN also requires
    # the exact Python product seam that the OpenCode helper invokes to execute.
    checks=parsed.get("contract_checks") or {}
    static_ok=isinstance(checks,dict) and all(bool(v) for v in checks.values())
    if not static_ok: return False
    runtime=root/"workspace-template"/"ai-test"/"runtime"
    env={**__import__("os").environ,"PYTHONPATH":str(runtime)}
    proc=subprocess.run([sys.executable,"-m","aitest_runtime.product_entry","g5","--role","DIAGNOSIS","--action","status","--payload","{}"],cwd=str(root/"workspace-template"),env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    result=parse_last_json(proc.stdout)
    return proc.returncode==0 and isinstance(result,dict) and result.get("truth_source")=="R1_EVENT_STREAM"


def oracle_shape(root: Path, filename: str, parsed: dict[str, Any] | None) -> tuple[bool,bool,bool]:
    if not isinstance(parsed,dict): return False,False,False
    current_truth=parsed.get("truthful_red") is True and parsed.get("red_kind")=="MISSING_G5_INTEGRATION"
    if filename in RUNTIME_ORACLE_SUITES:
        contract=parsed.get("oracle_contract") or {}
        future_runtime=isinstance(contract,dict) and contract.get("future_green_requires_real_runtime") is True
        runtime_green=parsed.get("runtime_green_evidence") is True
        return future_runtime,current_truth,runtime_green
    if filename=="test_g5_product_path.py": return True,current_truth,product_runtime_green(parsed)
    if filename=="test_g5_worker_binding_and_recovery.py": return True,current_truth,worker_runtime_green(parsed)
    if filename=="test_g5_opencode_surface.py": return True,current_truth,opencode_runtime_green(root,parsed)
    return False,current_truth,False


def run_suite(root: Path,test_dir: Path,filename: str,mode: str) -> dict[str,Any]:
    started=time.monotonic(); proc=subprocess.run([sys.executable,str(test_dir/filename)],cwd=str(test_dir),text=True,encoding="utf-8",errors="replace",stdout=subprocess.PIPE,stderr=subprocess.STDOUT); duration=round(time.monotonic()-started,3); parsed=parse_last_json(proc.stdout)
    future_runtime,current_truth,runtime_green=oracle_shape(root,filename,parsed)
    if mode=="red":
        accepted=(proc.returncode!=0 and isinstance(parsed,dict) and parsed.get("status")=="FAIL" and parsed.get("fixture_ok") is True and parsed.get("truthful_red") is True and parsed.get("red_kind")=="MISSING_G5_INTEGRATION" and bool(parsed.get("missing_contract_checks")) and future_runtime and current_truth and not runtime_green)
    else:
        accepted=(proc.returncode==0 and isinstance(parsed,dict) and parsed.get("status")=="PASS" and parsed.get("fixture_ok") is True and not parsed.get("missing_contract_checks") and future_runtime and runtime_green)
    return {"file":filename,"mode":mode,"returncode":proc.returncode,"duration_sec":duration,"accepted":accepted,"future_green_requires_real_runtime":future_runtime,"current_red_is_truthful":current_truth,"runtime_green_evidence":runtime_green,"parsed":parsed,"output_tail":proc.stdout[-6000:]}


def main()->int:
    parser=argparse.ArgumentParser(description="Canonical additive G5 EC0-EC7 validation runner"); parser.add_argument("--root",default="."); parser.add_argument("--mode",choices=("red","green"),default="red"); parser.add_argument("--output",default=None); args=parser.parse_args()
    root=Path(args.root).resolve(); test_dir=root/"workspace-template"/".pfc-internal-field-validation"/"tests"; frozen_runner=root/FROZEN_G1_G4_RUNNER_PATH; frozen_blob=git_blob_sha(frozen_runner); frozen_runner_unchanged=frozen_blob==FROZEN_G1_G4_RUNNER_BLOB
    suites=[run_suite(root,test_dir,f,args.mode) for f in SUITES]; all_suites_accepted=all(x["accepted"] for x in suites); status="PASS" if frozen_runner_unchanged and len(suites)==6 and all_suites_accepted else "FAIL"
    result={"status":status,"mode":args.mode,"truth_source":"CONSTRUCTION_VALIDATION_EVIDENCE","suite_count":len(suites),"all_g5_suites_accepted":all_suites_accepted,"ec0_truthful_red_frozen":args.mode=="red" and status=="PASS","g5_green":args.mode=="green" and status=="PASS","green_requires_runtime_behavior_in_every_suite":all(x["future_green_requires_real_runtime"] for x in suites),"frozen_g1_g4_regression_runner":{"path":FROZEN_G1_G4_RUNNER_PATH,"expected_blob":FROZEN_G1_G4_RUNNER_BLOB,"observed_blob":frozen_blob,"unchanged":frozen_runner_unchanged,"authority":"G1_G4_REGRESSION_ONLY","executed_by_this_runner":False,"note":"Historical g5_defect_truth=HOLD is metadata only and is not G5 gate truth."},"suites":suites}
    text=json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if args.output:
        output=Path(args.output); output=output if output.is_absolute() else root/output; output.write_text(text,encoding="utf-8")
    print(text,end=""); return 0 if status=="PASS" else 1


if __name__=="__main__": raise SystemExit(main())
