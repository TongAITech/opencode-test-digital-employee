from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import psycopg2
import redis


def _postgres():
    return psycopg2.connect(
        host=os.environ.get("RC8_TEST_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("RC8_TEST_PG_PORT", "5432")),
        dbname=os.environ.get("RC8_TEST_PG_DB", "rc8test"),
        user=os.environ.get("RC8_TEST_PG_USER", "rc8"),
        password=os.environ.get("RC8_TEST_PG_PASSWORD", "rc8"),
        connect_timeout=5,
    )


def _redis():
    return redis.Redis(
        host=os.environ.get("RC8_TEST_REDIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("RC8_TEST_REDIS_PORT", "6379")),
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


def before_restart() -> dict:
    run_id = os.environ.get("RC8_INFRA_RUN_ID") or ("infra-" + uuid.uuid4().hex[:12])

    pg = _postgres()
    pg.autocommit = True
    with pg.cursor() as cur:
        cur.execute("SELECT version()")
        pg_version = cur.fetchone()[0]
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS rc8_infra_probe (
                probe_id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "INSERT INTO rc8_infra_probe(probe_id, payload) VALUES (%s, %s::jsonb) "
            "ON CONFLICT (probe_id) DO UPDATE SET payload = EXCLUDED.payload",
            (run_id, json.dumps({"phase": "before-restart", "truth": "postgres-real"})),
        )
        cur.execute("SELECT payload->>'truth' FROM rc8_infra_probe WHERE probe_id=%s", (run_id,))
        assert cur.fetchone()[0] == "postgres-real"

    # Verify transaction rollback is real and visible from a second transaction.
    tx = _postgres()
    tx.autocommit = False
    rollback_id = run_id + "-rollback"
    with tx.cursor() as cur:
        cur.execute(
            "INSERT INTO rc8_infra_probe(probe_id, payload) VALUES (%s, %s::jsonb)",
            (rollback_id, json.dumps({"must": "rollback"})),
        )
    tx.rollback()
    tx.close()
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM rc8_infra_probe WHERE probe_id=%s", (rollback_id,))
        assert cur.fetchone()[0] == 0
    pg.close()

    rd = _redis()
    assert rd.ping() is True
    redis_version = rd.info("server")["redis_version"]

    # TTL semantics.
    ttl_key = run_id + ":ttl"
    rd.set(ttl_key, "ephemeral", ex=1)
    assert rd.get(ttl_key) == "ephemeral"
    time.sleep(1.3)
    assert rd.get(ttl_key) is None

    # Lease semantics used by RC8 resource/work-item coordination.
    lease_key = run_id + ":lease"
    assert rd.set(lease_key, "node-a", nx=True, ex=30) is True
    assert rd.set(lease_key, "node-b", nx=True, ex=30) is None
    assert rd.get(lease_key) == "node-a"

    # Queue semantics.
    queue_key = run_id + ":queue"
    rd.delete(queue_key)
    rd.rpush(queue_key, "work-1", "work-2")
    assert rd.lpop(queue_key) == "work-1"
    assert rd.lpop(queue_key) == "work-2"

    # Persistence marker. GitHub workflow performs SAVE then restarts the service container.
    durable_key = run_id + ":durable"
    rd.set(durable_key, "redis-real")
    assert rd.save() is True
    rd.close()

    return {
        "status": "RC8_INFRA_BEFORE_RESTART_PASS",
        "run_id": run_id,
        "postgres_version": pg_version,
        "redis_version": redis_version,
        "postgres_transaction_rollback": True,
        "redis_ttl": True,
        "redis_lease_nx": True,
        "redis_queue": True,
        "durable_marker_written": True,
    }


def after_restart(run_id: str) -> dict:
    if not run_id:
        raise SystemExit("RC8_INFRA_RUN_ID_REQUIRED")

    pg = _postgres()
    with pg.cursor() as cur:
        cur.execute("SELECT payload->>'truth' FROM rc8_infra_probe WHERE probe_id=%s", (run_id,))
        row = cur.fetchone()
        assert row is not None and row[0] == "postgres-real"
    pg.close()

    rd = _redis()
    deadline = time.time() + 10
    while True:
        try:
            if rd.ping():
                break
        except redis.RedisError:
            pass
        if time.time() >= deadline:
            raise AssertionError("REDIS_NOT_READY_AFTER_RESTART")
        time.sleep(0.25)
    assert rd.get(run_id + ":durable") == "redis-real"
    assert rd.get(run_id + ":lease") == "node-a"
    rd.close()

    return {
        "status": "RC8_INFRA_AFTER_RESTART_PASS",
        "run_id": run_id,
        "postgres_restart_persistence": True,
        "redis_restart_persistence": True,
        "redis_lease_survived_restart": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before-restart", "after-restart"), required=True)
    args = parser.parse_args()
    result = before_restart() if args.phase == "before-restart" else after_restart(os.environ.get("RC8_INFRA_RUN_ID", ""))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
