from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .common import AI_ROOT, DB_PATH, VERSION, ensure_dirs, now_iso

SCHEMA = r'''
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  profile TEXT NOT NULL,
  root_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'INITIALIZING',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS systems (
  system_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT 'UNKNOWN',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);
CREATE TABLE IF NOT EXISTS environments (
  environment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  environment_type TEXT NOT NULL DEFAULT 'TEST',
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);
CREATE TABLE IF NOT EXISTS repositories (
  repository_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  full_name TEXT NOT NULL,
  local_path TEXT NOT NULL,
  remote_url TEXT NOT NULL DEFAULT 'UNKNOWN',
  default_branch TEXT NOT NULL DEFAULT 'UNKNOWN',
  current_branch TEXT NOT NULL DEFAULT 'UNKNOWN',
  head_sha TEXT NOT NULL DEFAULT 'UNKNOWN',
  system_id TEXT,
  module_name TEXT,
  discovered_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, full_name),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);
CREATE TABLE IF NOT EXISTS releases (
  release_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  release_branch TEXT NOT NULL DEFAULT 'UNKNOWN',
  status TEXT NOT NULL DEFAULT 'OPEN',
  source_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);
CREATE TABLE IF NOT EXISTS requirements (
  requirement_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  source_hash TEXT,
  source_ref TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(release_id) REFERENCES releases(release_id)
);
CREATE TABLE IF NOT EXISTS version_ssts (
  release_id TEXT NOT NULL,
  sst_id TEXT NOT NULL,
  relation_type TEXT NOT NULL DEFAULT 'VERSION_SCOPE',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  source_ref TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(release_id, sst_id)
);
CREATE TABLE IF NOT EXISTS requirement_ssts (
  requirement_id TEXT NOT NULL,
  sst_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  owner_system_id TEXT,
  implementation_system_id TEXT,
  repository_id TEXT,
  module_name TEXT,
  feature_branch TEXT NOT NULL DEFAULT 'UNKNOWN',
  release_branch TEXT NOT NULL DEFAULT 'UNKNOWN',
  commit_range TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  source_ref TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(requirement_id, sst_id)
);
CREATE TABLE IF NOT EXISTS sst_quality_scope (
  requirement_id TEXT NOT NULL,
  sst_id TEXT NOT NULL,
  performance_required INTEGER NOT NULL DEFAULT 0,
  performance_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
  security_requirement_identified INTEGER NOT NULL DEFAULT 0,
  security_design_review_required INTEGER NOT NULL DEFAULT 0,
  security_design_review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
  security_test_required INTEGER NOT NULL DEFAULT 0,
  security_test_review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
  source_ref TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(requirement_id, sst_id)
);
CREATE TABLE IF NOT EXISTS connectors (
  connector_id TEXT PRIMARY KEY,
  project_id TEXT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  adapter_path TEXT,
  status TEXT NOT NULL DEFAULT 'NOT_CONFIGURED',
  config_json TEXT NOT NULL DEFAULT '{}',
  secret_ref TEXT,
  last_checked_at TEXT,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS auth_profiles (
  auth_profile_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  environment_id TEXT,
  system_id TEXT,
  name TEXT NOT NULL,
  browser_profile_ref TEXT,
  secret_ref TEXT,
  status TEXT NOT NULL DEFAULT 'UNKNOWN',
  expires_at TEXT,
  last_verified_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS truth_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  kind TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  valid_until TEXT,
  status TEXT NOT NULL DEFAULT 'CURRENT'
);
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  sst_id TEXT,
  kind TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  cache_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  media_type TEXT,
  parse_status TEXT NOT NULL DEFAULT 'PENDING',
  text_path TEXT,
  fetched_at TEXT NOT NULL,
  parsed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS submissions (
  submission_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT NOT NULL,
  environment_id TEXT,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deployments (
  deployment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gates (
  gate_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  sst_id TEXT,
  gate_type TEXT NOT NULL,
  status TEXT NOT NULL,
  decision TEXT,
  reviewer TEXT,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  reason TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
  mission_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  campaign_id TEXT,
  mission_type TEXT NOT NULL DEFAULT 'TEST',
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  plan_version INTEGER NOT NULL DEFAULT 0,
  current_step_id TEXT,
  resume_state TEXT,
  blocker TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS mission_plans (
  mission_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  plan_hash TEXT NOT NULL,
  PRIMARY KEY(mission_id, version)
);
CREATE TABLE IF NOT EXISTS mission_steps (
  step_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  plan_version INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  title TEXT NOT NULL,
  capability_id TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  role_required TEXT NOT NULL DEFAULT 'EXECUTOR',
  input_json TEXT NOT NULL DEFAULT '{}',
  expected_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  blocker TEXT,
  started_at TEXT,
  completed_at TEXT,
  UNIQUE(mission_id, plan_version, ordinal)
);
CREATE TABLE IF NOT EXISTS mission_events (
  event_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_sessions (
  worker_session_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  worker_role TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_session_id TEXT,
  status TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  compaction_count INTEGER NOT NULL DEFAULT 0,
  context_hash TEXT,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  worker_session_id TEXT,
  state TEXT NOT NULL,
  current_step_id TEXT,
  context_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_tasks (
  human_task_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  step_id TEXT,
  task_type TEXT NOT NULL,
  title TEXT NOT NULL,
  requested_action TEXT NOT NULL,
  assigned_to TEXT,
  status TEXT NOT NULL,
  resume_state TEXT NOT NULL,
  resume_step_id TEXT,
  human_comment TEXT,
  human_evidence_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  browser_session_id TEXT,
  created_at TEXT NOT NULL,
  claimed_at TEXT,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS browser_sessions (
  browser_session_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  mission_id TEXT,
  human_task_id TEXT,
  environment_id TEXT,
  auth_profile_id TEXT,
  mode TEXT NOT NULL,
  lease_owner TEXT NOT NULL,
  status TEXT NOT NULL,
  start_url TEXT,
  allowed_domains_json TEXT NOT NULL DEFAULT '[]',
  profile_path TEXT NOT NULL,
  debug_port INTEGER,
  process_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS browser_events (
  browser_event_id TEXT PRIMARY KEY,
  browser_session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  page_url TEXT,
  selector TEXT,
  semantic_name TEXT,
  value_repr TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  mission_id TEXT,
  run_id TEXT,
  step_id TEXT,
  channel TEXT NOT NULL,
  status TEXT NOT NULL,
  source_ref TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  sha256 TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  observation_id TEXT PRIMARY KEY,
  mission_id TEXT,
  run_id TEXT,
  step_id TEXT,
  requirement_id TEXT,
  sst_id TEXT,
  test_layer TEXT,
  dimension TEXT,
  expected_json TEXT NOT NULL DEFAULT '{}',
  actual_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  build_ref TEXT,
  deployment_ref TEXT,
  status TEXT NOT NULL DEFAULT 'OBSERVED',
  correlation_signature TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnoses (
  diagnosis_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL,
  classification TEXT NOT NULL,
  confidence TEXT NOT NULL,
  root_component TEXT,
  root_cause TEXT,
  excluded_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  cat_used INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS defects (
  defect_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  requirement_id TEXT,
  primary_sst_id TEXT,
  title TEXT NOT NULL,
  severity TEXT NOT NULL,
  defect_type TEXT NOT NULL,
  status TEXT NOT NULL,
  first_detected_layer TEXT,
  detected_layers_json TEXT NOT NULL DEFAULT '[]',
  root_component TEXT,
  root_cause TEXT,
  confirmation_mode TEXT NOT NULL,
  confirmed_by TEXT,
  confirmed_at TEXT,
  fix_commit TEXT,
  fix_build TEXT,
  fix_deployment TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS defect_observations (
  defect_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  PRIMARY KEY(defect_id, observation_id)
);
CREATE TABLE IF NOT EXISTS verification_obligations (
  obligation_id TEXT PRIMARY KEY,
  defect_id TEXT NOT NULL,
  test_layer TEXT NOT NULL,
  dimension TEXT NOT NULL,
  scope_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'PENDING',
  retest_mission_id TEXT,
  result_ref TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_layers (
  layer_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applicability (
  applicability_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  sst_id TEXT,
  layer_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  status TEXT NOT NULL,
  rationale TEXT NOT NULL,
  source_ref TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(requirement_id, sst_id, layer_id, dimension)
);
CREATE TABLE IF NOT EXISTS campaigns (
  campaign_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  campaign_type TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS campaign_items (
  item_id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  sst_id TEXT,
  layer_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  status TEXT NOT NULL,
  depends_on_json TEXT NOT NULL DEFAULT '[]',
  mission_id TEXT,
  rationale TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduler_events (
  scheduler_event_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  release_id TEXT,
  requirement_id TEXT,
  sst_id TEXT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL,
  processed_at TEXT
);
CREATE TABLE IF NOT EXISTS test_cases (
  case_id TEXT PRIMARY KEY,
  requirement_id TEXT NOT NULL,
  sst_id TEXT,
  layer_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  contract_json TEXT NOT NULL,
  asset_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_runs (
  run_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  requirement_id TEXT,
  environment_id TEXT,
  status TEXT NOT NULL,
  baseline_fingerprint TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_results (
  run_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(run_id, case_id)
);
CREATE TABLE IF NOT EXISTS teaching_events (
  teaching_event_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  subject TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  teacher TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_records (
  knowledge_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_json TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  confidence TEXT NOT NULL,
  status TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_records (
  skill_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  source_ref TEXT,
  replay_status TEXT NOT NULL DEFAULT 'NOT_RUN',
  regression_status TEXT NOT NULL DEFAULT 'NOT_RUN',
  reviewed_by TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, name, version)
);
CREATE TABLE IF NOT EXISTS capability_audit (
  audit_id TEXT PRIMARY KEY,
  mission_id TEXT,
  step_id TEXT,
  actor TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_json TEXT,
  created_at TEXT NOT NULL
);
'''


def _dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def connect(path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    db = path or DB_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(path: Path | None = None) -> Path:
    db = path or DB_PATH
    conn = connect(db)
    try:
        conn.executescript(SCHEMA)
        # Additive schema evolution for early V1.11 pilot workspaces.  The
        # runtime never drops or rewrites user data during initialization.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(human_tasks)").fetchall()}
        if "metadata_json" not in columns:
            conn.execute("ALTER TABLE human_tasks ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (VERSION,))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('initialized_at',COALESCE((SELECT value FROM meta WHERE key='initialized_at'),?))", (now_iso(),))
        conn.commit()
    finally:
        conn.close()
    return db


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: Iterable[Any] = (), *, path: Path | None = None) -> None:
    with transaction(path) as conn:
        conn.execute(sql, tuple(params))


def one(sql: str, params: Iterable[Any] = (), *, path: Path | None = None) -> dict[str, Any] | None:
    conn = connect(path)
    try:
        return conn.execute(sql, tuple(params)).fetchone()
    finally:
        conn.close()


def all_rows(sql: str, params: Iterable[Any] = (), *, path: Path | None = None) -> list[dict[str, Any]]:
    conn = connect(path)
    try:
        return list(conn.execute(sql, tuple(params)).fetchall())
    finally:
        conn.close()


def upsert(table: str, key_columns: list[str], record: dict[str, Any], *, path: Path | None = None) -> None:
    cols = list(record)
    values = [record[c] for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conflict = ",".join(key_columns)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in key_columns)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT({conflict}) DO UPDATE SET {updates}"
    with transaction(path) as conn:
        conn.execute(sql, values)


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def jload(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)
