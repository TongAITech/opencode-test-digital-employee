from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import artifacts, bootstrap, browser, capability, connectors, defects, doctor, human, knowledge, ledger, migration, mission, project, quality, repository, reporting, scheduler, session, skills, teaching, truth
from .common import VERSION, pretty_json
from .r1_5 import ControlPlane, R15Error, RecoveryRequest, diagnose_failure, install_workspace, launch_runtime, recover, validate_startup
from .server import serve, serve_r1_5
from .storage import initialize


def _json(text: str | None, default: Any = None) -> Any:
    if text in (None, ""):
        return default
    path = Path(text)
    if path.exists() and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(text)


def _print(value: Any) -> None:
    print(pretty_json(value))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aitest", description=f"AI Test Runtime V{VERSION}")
    p.add_argument("--json", action="store_true", help="reserved for compatibility; output is JSON by default")
    sp = p.add_subparsers(dest="command", required=True)

    sp.add_parser("init-db")
    d = sp.add_parser("doctor"); d.add_argument("--project-id"); d.add_argument("--field-validation-profile")
    st = sp.add_parser("start"); st.add_argument("--project-id")
    sv = sp.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8765)

    x=sp.add_parser("r1-5-install"); x.add_argument("--package-root", required=True); x.add_argument("--destination", required=True)
    x=sp.add_parser("r1-5-validate"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config")
    x=sp.add_parser("r1-5-launch"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config")
    x=sp.add_parser("r1-5-health"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config"); x.add_argument("--mission-id")
    x=sp.add_parser("r1-5-project"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config"); x.add_argument("--mission-id", required=True)
    x=sp.add_parser("r1-5-command"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config"); x.add_argument("--command", required=True)
    x=sp.add_parser("r1-5-recover"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config"); x.add_argument("--recovery-id", required=True); x.add_argument("--operation", required=True); x.add_argument("--mission-id", required=True); x.add_argument("--authorization-id", required=True); x.add_argument("--recovery-command")
    x=sp.add_parser("r1-5-diagnostics"); x.add_argument("--correlation-id", required=True); x.add_argument("--code", required=True); x.add_argument("--message", required=True); x.add_argument("--evidence")
    x=sp.add_parser("r1-5-serve"); x.add_argument("--workspace-root", default=str(Path.cwd())); x.add_argument("--package-root"); x.add_argument("--config"); x.add_argument("--host", default="127.0.0.1"); x.add_argument("--port", type=int, default=8765)

    x=sp.add_parser("project-init"); x.add_argument("--name", required=True); x.add_argument("--profile", default="GENERIC"); x.add_argument("--root", required=True); x.add_argument("--project-id"); x.add_argument("--config")
    sp.add_parser("project-list")
    x=sp.add_parser("project-status"); x.add_argument("--project-id", required=True)
    x=sp.add_parser("system-add"); x.add_argument("--project-id", required=True); x.add_argument("--system-id", required=True); x.add_argument("--name", required=True); x.add_argument("--description", default=""); x.add_argument("--owner", default="UNKNOWN")
    x=sp.add_parser("environment-add"); x.add_argument("--project-id", required=True); x.add_argument("--environment-id", required=True); x.add_argument("--name", required=True); x.add_argument("--type", default="TEST"); x.add_argument("--config")
    x=sp.add_parser("connector-add"); x.add_argument("--project-id"); x.add_argument("--connector-id", required=True); x.add_argument("--kind", required=True); x.add_argument("--name", required=True); x.add_argument("--adapter-path"); x.add_argument("--config"); x.add_argument("--secret-ref")
    x=sp.add_parser("connector-check"); x.add_argument("--connector-id", required=True)
    x=sp.add_parser("auth-add"); x.add_argument("--project-id", required=True); x.add_argument("--auth-profile-id", required=True); x.add_argument("--name", required=True); x.add_argument("--environment-id"); x.add_argument("--system-id"); x.add_argument("--secret-ref"); x.add_argument("--browser-profile-ref"); x.add_argument("--metadata")

    x=sp.add_parser("repo-discover"); x.add_argument("--project-id", required=True); x.add_argument("--root", required=True); x.add_argument("--max-depth", type=int, default=4)
    x=sp.add_parser("repo-list"); x.add_argument("--project-id", required=True)
    x=sp.add_parser("repo-refresh"); x.add_argument("--project-id", required=True); x.add_argument("--repository-id")

    x=sp.add_parser("release-add"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--name", required=True); x.add_argument("--release-branch", default="UNKNOWN"); x.add_argument("--source-ref"); x.add_argument("--metadata")
    x=sp.add_parser("requirement-add"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--requirement-id", required=True); x.add_argument("--title", required=True); x.add_argument("--source-ref"); x.add_argument("--source-hash"); x.add_argument("--metadata")
    x=sp.add_parser("requirement-baseline"); x.add_argument("--requirement-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--evidence")
    x=sp.add_parser("version-sst-add"); x.add_argument("--release-id", required=True); x.add_argument("--sst-id", required=True); x.add_argument("--relation-type", default="VERSION_SCOPE"); x.add_argument("--source-ref"); x.add_argument("--metadata")
    x=sp.add_parser("requirement-sst-add"); x.add_argument("--requirement-id", required=True); x.add_argument("--sst-id", required=True); x.add_argument("--title", default=""); x.add_argument("--owner-system-id"); x.add_argument("--implementation-system-id"); x.add_argument("--repository-id"); x.add_argument("--module-name"); x.add_argument("--feature-branch", default="UNKNOWN"); x.add_argument("--release-branch", default="UNKNOWN"); x.add_argument("--commit-range"); x.add_argument("--source-ref"); x.add_argument("--metadata")
    x=sp.add_parser("quality-scope-set"); x.add_argument("--requirement-id", required=True); x.add_argument("--sst-id", required=True); x.add_argument("--performance-required", action="store_true"); x.add_argument("--performance-status"); x.add_argument("--security-requirement-identified", action="store_true"); x.add_argument("--security-design-review-required", action="store_true"); x.add_argument("--security-design-review-status"); x.add_argument("--security-test-required", action="store_true"); x.add_argument("--security-test-review-status"); x.add_argument("--source-ref")
    x=sp.add_parser("truth-snapshot"); x.add_argument("--project-id", required=True); x.add_argument("--kind", required=True); x.add_argument("--source-ref", required=True); x.add_argument("--payload", required=True); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--valid-until")
    x=sp.add_parser("submission-import"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--payload", required=True); x.add_argument("--environment-id")
    x=sp.add_parser("deployment-import"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--environment-id", required=True); x.add_argument("--payload", required=True)
    x=sp.add_parser("baseline-reconcile"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--requirement-id", required=True); x.add_argument("--environment-id", required=True)
    x=sp.add_parser("gate-set"); x.add_argument("--project-id", required=True); x.add_argument("--gate-type", required=True); x.add_argument("--status", required=True); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--sst-id"); x.add_argument("--decision"); x.add_argument("--reviewer"); x.add_argument("--evidence"); x.add_argument("--reason")

    x=sp.add_parser("artifact-fetch"); x.add_argument("--project-id", required=True); x.add_argument("--kind", required=True); x.add_argument("--source-ref", required=True); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--sst-id"); x.add_argument("--allowed-hosts"); x.add_argument("--metadata")

    x=sp.add_parser("mission-create"); x.add_argument("--project-id", required=True); x.add_argument("--title", required=True); x.add_argument("--created-by", default="human"); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--campaign-id"); x.add_argument("--mission-type", default="TEST"); x.add_argument("--metadata")
    x=sp.add_parser("mission-status"); x.add_argument("--mission-id", required=True)
    x=sp.add_parser("mission-list"); x.add_argument("--project-id", required=True); x.add_argument("--states")
    x=sp.add_parser("mission-transition"); x.add_argument("--mission-id", required=True); x.add_argument("--state", required=True); x.add_argument("--actor", required=True); x.add_argument("--reason", default=""); x.add_argument("--blocker"); x.add_argument("--force", action="store_true")
    x=sp.add_parser("mission-plan"); x.add_argument("--mission-id", required=True); x.add_argument("--steps", required=True); x.add_argument("--actor", default="aitest-planner"); x.add_argument("--reason", default="INITIAL_PLAN")
    x=sp.add_parser("mission-replan"); x.add_argument("--mission-id", required=True); x.add_argument("--actor", default="human"); x.add_argument("--reason", required=True)
    x=sp.add_parser("mission-continue"); x.add_argument("--mission-id", required=True); x.add_argument("--actor", default="human")
    x=sp.add_parser("mission-checkpoint"); x.add_argument("--mission-id", required=True); x.add_argument("--reason", required=True); x.add_argument("--worker-session-id")
    x=sp.add_parser("capability-invoke"); x.add_argument("--capability-id", required=True); x.add_argument("--actor", required=True); x.add_argument("--request", required=True); x.add_argument("--mission-id"); x.add_argument("--step-id")

    x=sp.add_parser("session-open"); x.add_argument("--mission-id", required=True); x.add_argument("--role", required=True); x.add_argument("--provider", default="AUTO"); x.add_argument("--opencode-url", default="http://127.0.0.1:4096")
    x=sp.add_parser("session-health"); x.add_argument("--worker-session-id", required=True); x.add_argument("--opencode-url", default="http://127.0.0.1:4096")
    x=sp.add_parser("session-rotate"); x.add_argument("--worker-session-id", required=True); x.add_argument("--reason", required=True); x.add_argument("--opencode-url", default="http://127.0.0.1:4096")
    x=sp.add_parser("session-recover"); x.add_argument("--mission-id", required=True); x.add_argument("--opencode-url", default="http://127.0.0.1:4096"); x.add_argument("--roles")

    x=sp.add_parser("preflight"); x.add_argument("--mission-id", required=True); x.add_argument("--environment-id", required=True)
    x=sp.add_parser("execution-authorize"); x.add_argument("--mission-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--decision", required=True); x.add_argument("--reason", default="")
    x=sp.add_parser("step-execute"); x.add_argument("--mission-id", required=True); x.add_argument("--actor", default="aitest-executor")
    x=sp.add_parser("step-evaluate"); x.add_argument("--mission-id", required=True); x.add_argument("--actor", default="aitest-evaluator"); x.add_argument("--status"); x.add_argument("--reason", default="")
    x=sp.add_parser("mission-finalize"); x.add_argument("--mission-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--decision", required=True); x.add_argument("--reason", default="")

    x=sp.add_parser("human-list"); x.add_argument("--project-id", required=True); x.add_argument("--statuses")
    x=sp.add_parser("human-create"); x.add_argument("--mission-id", required=True); x.add_argument("--type", required=True); x.add_argument("--title", required=True); x.add_argument("--requested-action", required=True); x.add_argument("--step-id"); x.add_argument("--assigned-to")
    x=sp.add_parser("human-claim"); x.add_argument("--task-id", required=True); x.add_argument("--user-id", required=True)
    x=sp.add_parser("human-complete"); x.add_argument("--task-id", required=True); x.add_argument("--user-id", required=True); x.add_argument("--comment", default=""); x.add_argument("--evidence")

    x=sp.add_parser("browser-launch"); x.add_argument("--project-id", required=True); x.add_argument("--mode", default="TEACH"); x.add_argument("--browser-session-id"); x.add_argument("--mission-id"); x.add_argument("--human-task-id"); x.add_argument("--environment-id"); x.add_argument("--auth-profile-id"); x.add_argument("--start-url"); x.add_argument("--allowed-domains"); x.add_argument("--browser-executable"); x.add_argument("--dry-run", action="store_true")
    x=sp.add_parser("browser-lease"); x.add_argument("--browser-session-id", required=True); x.add_argument("--from-owner", required=True); x.add_argument("--to-owner", required=True)
    x=sp.add_parser("browser-trace"); x.add_argument("--browser-session-id", required=True)
    x=sp.add_parser("browser-close"); x.add_argument("--browser-session-id", required=True)

    sp.add_parser("scheduler-seed")
    x=sp.add_parser("applicability-compute"); x.add_argument("--project-id", required=True); x.add_argument("--release-id", required=True); x.add_argument("--requirement-id", required=True); x.add_argument("--source-ref", default="RUNTIME_RULES")
    x=sp.add_parser("campaign-create"); x.add_argument("--project-id", required=True); x.add_argument("--type", required=True); x.add_argument("--title", required=True); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--metadata")
    x=sp.add_parser("campaign-materialize"); x.add_argument("--campaign-id", required=True); x.add_argument("--actor", default="aitest-scheduler")
    x=sp.add_parser("campaign-dispatch"); x.add_argument("--campaign-id", required=True); x.add_argument("--actor", default="aitest-scheduler")
    x=sp.add_parser("scheduler-event"); x.add_argument("--project-id", required=True); x.add_argument("--event-type", required=True); x.add_argument("--release-id"); x.add_argument("--requirement-id"); x.add_argument("--sst-id"); x.add_argument("--payload")
    x=sp.add_parser("scheduler-process"); x.add_argument("--project-id", required=True); x.add_argument("--limit", type=int, default=100)

    x=sp.add_parser("observation-create"); x.add_argument("--mission-id"); x.add_argument("--run-id"); x.add_argument("--step-id"); x.add_argument("--requirement-id"); x.add_argument("--sst-id"); x.add_argument("--test-layer"); x.add_argument("--dimension"); x.add_argument("--expected", required=True); x.add_argument("--actual", required=True); x.add_argument("--evidence"); x.add_argument("--build-ref"); x.add_argument("--deployment-ref")
    x=sp.add_parser("observation-diagnose"); x.add_argument("--observation-id", required=True); x.add_argument("--actor", default="aitest-diagnosis"); x.add_argument("--classification"); x.add_argument("--confidence"); x.add_argument("--root-component"); x.add_argument("--root-cause"); x.add_argument("--excluded"); x.add_argument("--cat-connector-id"); x.add_argument("--cat-query")
    x=sp.add_parser("defect-correlate"); x.add_argument("--project-id", required=True); x.add_argument("--observation-id", required=True); x.add_argument("--diagnosis-id", required=True); x.add_argument("--title", required=True); x.add_argument("--severity", default="S2")
    x=sp.add_parser("defect-list"); x.add_argument("--project-id", required=True); x.add_argument("--statuses")
    x=sp.add_parser("defect-confirm"); x.add_argument("--defect-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--decision", required=True); x.add_argument("--reason", default="")
    x=sp.add_parser("defect-fix"); x.add_argument("--defect-id", required=True); x.add_argument("--commit", required=True); x.add_argument("--build"); x.add_argument("--deployment"); x.add_argument("--actor", default="developer")
    x=sp.add_parser("defect-retest"); x.add_argument("--defect-id", required=True); x.add_argument("--actor", default="aitest-scheduler")
    x=sp.add_parser("defect-retest-result"); x.add_argument("--obligation-id", required=True); x.add_argument("--status", required=True); x.add_argument("--result-ref", required=True)
    x=sp.add_parser("defect-close"); x.add_argument("--defect-id", required=True); x.add_argument("--reviewer", required=True)

    x=sp.add_parser("teach"); x.add_argument("--project-id", required=True); x.add_argument("--type", required=True); x.add_argument("--subject", required=True); x.add_argument("--payload", required=True); x.add_argument("--teacher", required=True)
    x=sp.add_parser("teach-materialize"); x.add_argument("--teaching-event-id", required=True)
    x=sp.add_parser("teach-approve"); x.add_argument("--teaching-event-id", required=True); x.add_argument("--reviewer", required=True)
    x=sp.add_parser("knowledge-list"); x.add_argument("--project-id", required=True); x.add_argument("--status"); x.add_argument("--subject")
    x=sp.add_parser("knowledge-verify"); x.add_argument("--knowledge-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--confidence", default="HIGH")
    x=sp.add_parser("knowledge-invalidate"); x.add_argument("--knowledge-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--reason", required=True)
    x=sp.add_parser("skill-list"); x.add_argument("--project-id", required=True); x.add_argument("--status")
    x=sp.add_parser("skill-validate"); x.add_argument("--skill-id", required=True); x.add_argument("--replay-status"); x.add_argument("--regression-status"); x.add_argument("--evidence")
    x=sp.add_parser("skill-promote"); x.add_argument("--skill-id", required=True); x.add_argument("--reviewer", required=True)
    x=sp.add_parser("skill-reject"); x.add_argument("--skill-id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--reason", required=True)

    x=sp.add_parser("case-add"); x.add_argument("--case-id", required=True); x.add_argument("--requirement-id", required=True); x.add_argument("--layer-id", required=True); x.add_argument("--dimension", required=True); x.add_argument("--title", required=True); x.add_argument("--contract", required=True); x.add_argument("--sst-id")
    x=sp.add_parser("run-create"); x.add_argument("--mission-id", required=True); x.add_argument("--requirement-id"); x.add_argument("--environment-id"); x.add_argument("--baseline-fingerprint")
    x=sp.add_parser("run-record"); x.add_argument("--run-id", required=True); x.add_argument("--case-id", required=True); x.add_argument("--status", required=True); x.add_argument("--result")
    x=sp.add_parser("run-summary"); x.add_argument("--run-id", required=True); x.add_argument("--designed-total", type=int)
    x=sp.add_parser("run-complete"); x.add_argument("--run-id", required=True); x.add_argument("--designed-total", type=int)

    x=sp.add_parser("migrate"); x.add_argument("--source", required=True); x.add_argument("--project-name", required=True); x.add_argument("--profile", default="GENERIC"); x.add_argument("--project-root"); x.add_argument("--project-id")
    x=sp.add_parser("report"); x.add_argument("--project-id", required=True)
    return p


def dispatch(a: argparse.Namespace) -> Any:
    c=a.command
    if c=="init-db": return {"database": str(initialize()), "status": "READY"}
    if c=="doctor": return doctor.run(a.project_id, field_validation_profile=a.field_validation_profile)
    if c=="start": return bootstrap.start(a.project_id)
    if c=="serve": return serve(a.host,a.port)
    if c=="r1-5-install": return install_workspace(a.package_root,a.destination).to_dict()
    if c=="r1-5-validate": return validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config).to_dict()
    if c=="r1-5-launch": return launch_runtime(validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config)).to_dict()
    if c=="r1-5-health":
        plane=ControlPlane(launch_runtime(validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config)))
        return plane.health(a.mission_id).to_dict()
    if c=="r1-5-project":
        plane=ControlPlane(launch_runtime(validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config)))
        return plane.projection(a.mission_id).to_dict()
    if c=="r1-5-command":
        plane=ControlPlane(launch_runtime(validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config)))
        return plane.submit_command(_json(a.command,{})).to_dict()
    if c=="r1-5-recover":
        startup=validate_startup(a.workspace_root,package_root=a.package_root,configuration_path=a.config)
        launched=launch_runtime(startup)
        request=RecoveryRequest(a.recovery_id,a.operation,a.mission_id,a.authorization_id,startup.artifact.manifest_digest,startup.configuration.digest,_json(a.recovery_command,None))
        return recover(launched.runtime,startup,request).to_dict()
    if c=="r1-5-diagnostics":
        return diagnose_failure(R15Error(a.code,a.message),correlation_id=a.correlation_id,evidence=_json(a.evidence,{})).to_dict()
    if c=="r1-5-serve": return serve_r1_5(a.workspace_root,host=a.host,port=a.port,package_root=a.package_root,configuration_path=a.config)
    if c=="project-init": return project.init_project(a.name,a.profile,a.root,project_id=a.project_id,config=_json(a.config,{}))
    if c=="project-list": return project.list_projects()
    if c=="project-status": return project.project_status(a.project_id)
    if c=="system-add": return project.register_system(a.project_id,a.system_id,a.name,a.description,a.owner)
    if c=="environment-add": return project.register_environment(a.project_id,a.environment_id,a.name,a.type,_json(a.config,{}))
    if c=="connector-add": return project.register_connector(a.project_id,a.connector_id,a.kind,a.name,adapter_path=a.adapter_path,config=_json(a.config,{}),secret_ref=a.secret_ref)
    if c=="connector-check": return connectors.check(a.connector_id)
    if c=="auth-add": return project.register_auth_profile(a.project_id,a.auth_profile_id,a.name,environment_id=a.environment_id,system_id=a.system_id,browser_profile_ref=a.browser_profile_ref,secret_ref=a.secret_ref,metadata=_json(a.metadata,{}))
    if c=="repo-discover": return repository.discover(a.project_id,a.root,a.max_depth)
    if c=="repo-list": return repository.list_repositories(a.project_id)
    if c=="repo-refresh": return repository.refresh(a.project_id,a.repository_id)
    if c=="release-add": return truth.register_release(a.project_id,a.release_id,a.name,a.release_branch,a.source_ref,_json(a.metadata,{}))
    if c=="requirement-add": return truth.register_requirement(a.project_id,a.release_id,a.requirement_id,a.title,source_ref=a.source_ref,source_hash=a.source_hash,metadata=_json(a.metadata,{}))
    if c=="requirement-baseline": return truth.baseline_requirement(a.requirement_id,a.reviewer,_json(a.evidence,[]))
    if c=="version-sst-add": return truth.link_version_sst(a.release_id,a.sst_id,relation_type=a.relation_type,source_ref=a.source_ref,metadata=_json(a.metadata,{}))
    if c=="requirement-sst-add": return truth.link_requirement_sst(a.requirement_id,a.sst_id,title=a.title,owner_system_id=a.owner_system_id,implementation_system_id=a.implementation_system_id,repository_id=a.repository_id,module_name=a.module_name,feature_branch=a.feature_branch,release_branch=a.release_branch,commit_range=a.commit_range,source_ref=a.source_ref,metadata=_json(a.metadata,{}))
    if c=="quality-scope-set": return truth.set_quality_scope(a.requirement_id,a.sst_id,performance_required=a.performance_required,performance_status=a.performance_status,security_requirement_identified=a.security_requirement_identified,security_design_review_required=a.security_design_review_required,security_design_review_status=a.security_design_review_status,security_test_required=a.security_test_required,security_test_review_status=a.security_test_review_status,source_ref=a.source_ref)
    if c=="truth-snapshot": return truth.add_snapshot(a.project_id,a.kind,a.source_ref,_json(a.payload,{}),release_id=a.release_id,requirement_id=a.requirement_id,valid_until=a.valid_until)
    if c=="submission-import": return truth.import_submission(a.project_id,a.release_id,_json(a.payload,{}),environment_id=a.environment_id)
    if c=="deployment-import": return truth.import_deployment(a.project_id,a.release_id,a.environment_id,_json(a.payload,{}))
    if c=="baseline-reconcile": return truth.reconcile_baseline(a.project_id,a.release_id,a.requirement_id,a.environment_id)
    if c=="gate-set": return truth.gate_set(a.project_id,a.gate_type,a.status,release_id=a.release_id,requirement_id=a.requirement_id,sst_id=a.sst_id,decision=a.decision,reviewer=a.reviewer,evidence=_json(a.evidence,[]),reason=a.reason)
    if c=="artifact-fetch": return artifacts.fetch_artifact(a.project_id,a.kind,a.source_ref,release_id=a.release_id,requirement_id=a.requirement_id,sst_id=a.sst_id,allowed_hosts=_json(a.allowed_hosts,[]),metadata=_json(a.metadata,{}))
    if c=="mission-create": return mission.create_mission(a.project_id,a.title,a.created_by,release_id=a.release_id,requirement_id=a.requirement_id,campaign_id=a.campaign_id,mission_type=a.mission_type,metadata=_json(a.metadata,{}))
    if c=="mission-status": return mission.get_mission(a.mission_id)
    if c=="mission-list": return mission.list_missions(a.project_id,states=_json(a.states,None))
    if c=="mission-transition": return mission.transition(a.mission_id,a.state,a.actor,reason=a.reason,blocker=a.blocker,force=a.force)
    if c=="mission-plan": return mission.submit_plan(a.mission_id,_json(a.steps,[]),a.actor,reason=a.reason)
    if c=="mission-replan": return mission.request_replan(a.mission_id,a.actor,a.reason)
    if c=="mission-continue": return mission.continue_mission(a.mission_id,a.actor)
    if c=="mission-checkpoint": return mission.checkpoint(a.mission_id,a.reason,worker_session_id=a.worker_session_id)
    if c=="capability-invoke": return capability.invoke(a.capability_id,a.actor,_json(a.request,{}),mission_id=a.mission_id,step_id=a.step_id)
    if c=="session-open": return session.open_worker_session(a.mission_id,a.role,provider=a.provider,opencode_url=a.opencode_url)
    if c=="session-health": return session.refresh_health(a.worker_session_id,opencode_url=a.opencode_url)
    if c=="session-rotate": return session.rotate_worker_session(a.worker_session_id,reason=a.reason,opencode_url=a.opencode_url)
    if c=="session-recover": return session.recover_mission_sessions(a.mission_id,opencode_url=a.opencode_url,roles=_json(a.roles,None))
    if c=="preflight": return quality.evaluate_preflight(a.mission_id,a.environment_id)
    if c=="execution-authorize": return quality.authorize_execution(a.mission_id,a.reviewer,a.decision,a.reason)
    if c=="step-execute": return quality.execute_current_step(a.mission_id,a.actor)
    if c=="step-evaluate": return quality.evaluate_current_step(a.mission_id,a.actor,override_status=a.status,reason=a.reason)
    if c=="mission-finalize": return quality.finalize_mission(a.mission_id,a.reviewer,a.decision,a.reason)
    if c=="human-list": return human.list_tasks(a.project_id,statuses=_json(a.statuses,None))
    if c=="human-create": return human.create_task(a.mission_id,a.type,a.title,a.requested_action,step_id=a.step_id,assigned_to=a.assigned_to)
    if c=="human-claim": return human.claim_task(a.task_id,a.user_id)
    if c=="human-complete": return human.complete_task(a.task_id,a.user_id,comment=a.comment,evidence=_json(a.evidence,[]))
    if c=="browser-launch": return browser.launch_browser(a.project_id,a.mode,browser_session_id=a.browser_session_id,mission_id=a.mission_id,human_task_id=a.human_task_id,environment_id=a.environment_id,auth_profile_id=a.auth_profile_id,start_url=a.start_url,allowed_domains=_json(a.allowed_domains,[]),browser_executable=a.browser_executable,dry_run=a.dry_run)
    if c=="browser-lease": return browser.transfer_lease(a.browser_session_id,a.from_owner,a.to_owner)
    if c=="browser-trace": return browser.trace(a.browser_session_id)
    if c=="browser-close": return browser.close_browser_session(a.browser_session_id)
    if c=="scheduler-seed": return scheduler.seed_layers()
    if c=="applicability-compute": return scheduler.compute_applicability(a.project_id,a.release_id,a.requirement_id,source_ref=a.source_ref)
    if c=="campaign-create": return scheduler.create_campaign(a.project_id,a.type,a.title,release_id=a.release_id,requirement_id=a.requirement_id,metadata=_json(a.metadata,{}))
    if c=="campaign-materialize": return scheduler.materialize_campaign(a.campaign_id,a.actor)
    if c=="campaign-dispatch": return scheduler.dispatch_ready(a.campaign_id,a.actor)
    if c=="scheduler-event": return scheduler.ingest_event(a.project_id,a.event_type,release_id=a.release_id,requirement_id=a.requirement_id,sst_id=a.sst_id,payload=_json(a.payload,{}))
    if c=="scheduler-process": return scheduler.process_events(a.project_id,a.limit)
    if c=="observation-create": return defects.create_observation(mission_id=a.mission_id,run_id=a.run_id,step_id=a.step_id,requirement_id=a.requirement_id,sst_id=a.sst_id,test_layer=a.test_layer,dimension=a.dimension,expected=_json(a.expected,{}),actual=_json(a.actual,{}),evidence=_json(a.evidence,[]),build_ref=a.build_ref,deployment_ref=a.deployment_ref)
    if c=="observation-diagnose": return defects.diagnose_observation(a.observation_id,actor=a.actor,classification=a.classification,confidence=a.confidence or "MEDIUM",root_component=a.root_component,root_cause=a.root_cause,excluded=_json(a.excluded,[]),cat_query=_json(a.cat_query,{}))
    if c=="defect-correlate": return defects.correlate_defect(a.diagnosis_id,project_id=a.project_id,title=a.title,severity=a.severity)
    if c=="defect-list": return defects.list_defects(a.project_id,statuses=_json(a.statuses,None))
    if c=="defect-confirm": return defects.confirm_defect(a.defect_id,a.reviewer,a.decision,a.reason)
    if c=="defect-fix": return defects.register_fix(a.defect_id,a.commit,build=a.build,deployment=a.deployment,actor=a.actor)
    if c=="defect-retest": return defects.dispatch_retest(a.defect_id,a.actor)
    if c=="defect-retest-result": return defects.record_retest_result(a.obligation_id,a.status,a.result_ref)
    if c=="defect-close": return defects.close_defect(a.defect_id,a.reviewer)
    if c=="teach": return teaching.create_event(a.project_id,a.type,a.subject,_json(a.payload,{}),a.teacher)
    if c=="teach-materialize": return teaching.materialize(a.teaching_event_id)
    if c=="teach-approve": return teaching.approve(a.teaching_event_id,a.reviewer)
    if c=="knowledge-list": return knowledge.list_records(a.project_id,status=a.status,subject=a.subject)
    if c=="knowledge-verify": return knowledge.verify(a.knowledge_id,a.reviewer,confidence=a.confidence)
    if c=="knowledge-invalidate": return knowledge.invalidate(a.knowledge_id,a.reviewer,a.reason)
    if c=="skill-list": return skills.list_skills(a.project_id,status=a.status)
    if c=="skill-validate": return skills.record_validation(a.skill_id,replay_status=a.replay_status,regression_status=a.regression_status,evidence=_json(a.evidence,[]))
    if c=="skill-promote": return skills.promote(a.skill_id,a.reviewer)
    if c=="skill-reject": return skills.reject(a.skill_id,a.reviewer,a.reason)
    if c=="case-add": return quality.register_test_case(a.requirement_id,a.case_id,a.title,a.layer_id,a.dimension,_json(a.contract,{}),sst_id=a.sst_id)
    if c=="run-create": return ledger.create_run(a.mission_id,a.requirement_id,a.environment_id,a.baseline_fingerprint)
    if c=="run-record": return ledger.record(a.run_id,a.case_id,a.status,_json(a.result,{}))
    if c=="run-summary": return ledger.summarize(a.run_id,designed_total=a.designed_total)
    if c=="run-complete": return ledger.complete(a.run_id,designed_total=a.designed_total)
    if c=="migrate": return migration.import_legacy(a.source,project_name=a.project_name,profile=a.profile,project_root=a.project_root,project_id=a.project_id)
    if c=="report": return reporting.project_report(a.project_id)
    raise ValueError(f"unknown command: {c}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        if result is not None:
            _print(result)
        return 0
    except Exception as exc:
        _print({"ok": False, "error": type(exc).__name__, "message": str(exc), "command": args.command})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
