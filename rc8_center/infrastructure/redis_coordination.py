"""Redis coordination adapter for leases/queues/cache.

Redis is explicitly non-authoritative. Mission/TestRun/Attempt/Gap/Sufficiency
truth must survive Redis loss and be reconstructable from PostgreSQL + R1.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from redis import Redis


class RedisCoordination:
    def __init__(self, client: Redis, namespace: str = "rc8") -> None:
        self.client = client
        self.namespace = namespace.strip(":") or "rc8"

    @classmethod
    def from_url(cls, redis_url: str, namespace: str = "rc8") -> "RedisCoordination":
        return cls(Redis.from_url(redis_url, decode_responses=True), namespace=namespace)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def _key(self, *parts: str) -> str:
        return ":".join([self.namespace] + [str(part) for part in parts])

    def acquire_lease(self, lease_type: str, resource_id: str, owner_id: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("LEASE_TTL_MUST_BE_POSITIVE")
        key = self._key("lease", lease_type, resource_id)
        payload = json.dumps({"owner_id": owner_id, "acquired_at": int(time.time())}, sort_keys=True)
        return bool(self.client.set(key, payload, nx=True, ex=int(ttl_seconds)))

    def lease_owner(self, lease_type: str, resource_id: str) -> Optional[str]:
        raw = self.client.get(self._key("lease", lease_type, resource_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        return str(payload.get("owner_id") or "") or None

    def renew_lease(self, lease_type: str, resource_id: str, owner_id: str, ttl_seconds: int) -> bool:
        key = self._key("lease", lease_type, resource_id)
        raw = self.client.get(key)
        if raw is None:
            return False
        payload = json.loads(raw)
        if str(payload.get("owner_id") or "") != owner_id:
            return False
        payload["renewed_at"] = int(time.time())
        pipe = self.client.pipeline()
        pipe.set(key, json.dumps(payload, sort_keys=True), xx=True, ex=int(ttl_seconds))
        result = pipe.execute()
        return bool(result and result[0])

    def release_lease(self, lease_type: str, resource_id: str, owner_id: str) -> bool:
        key = self._key("lease", lease_type, resource_id)
        # Atomic compare-and-delete. Never let one node release another owner's lease.
        script = """
        local value = redis.call('GET', KEYS[1])
        if not value then return 0 end
        local decoded = cjson.decode(value)
        if decoded['owner_id'] ~= ARGV[1] then return -1 end
        return redis.call('DEL', KEYS[1])
        """
        result = int(self.client.eval(script, 1, key, owner_id))
        if result < 0:
            raise ValueError("LEASE_OWNER_MISMATCH")
        return result == 1

    def enqueue(self, queue_name: str, payload: Dict[str, Any]) -> int:
        return int(self.client.rpush(self._key("queue", queue_name), json.dumps(payload, sort_keys=True)))

    def dequeue(self, queue_name: str, timeout_seconds: int = 0) -> Optional[Dict[str, Any]]:
        key = self._key("queue", queue_name)
        if timeout_seconds > 0:
            result = self.client.blpop(key, timeout=int(timeout_seconds))
            if result is None:
                return None
            raw = result[1]
        else:
            raw = self.client.lpop(key)
            if raw is None:
                return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("QUEUE_PAYLOAD_MUST_BE_OBJECT")
        return payload

    def set_cache(self, cache_key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        self.client.set(self._key("cache", cache_key), json.dumps(payload, sort_keys=True), ex=int(ttl_seconds))

    def get_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        raw = self.client.get(self._key("cache", cache_key))
        if raw is None:
            return None
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
