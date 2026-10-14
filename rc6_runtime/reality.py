"""Canonical bank-reality registry for RC6 Wave 3.

Historical facts are migrated once. Missions consume the registry and perform
bounded freshness reconciliation instead of rediscovering the bank environment.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class RealityError(ValueError):
    pass


REALITY_KINDS = {
    "application", "repository", "environment", "database", "auth",
    "cat", "account", "route", "tool",
}
REALITY_STATUSES = {"READY", "STALE", "NEEDS_BINDING", "INVALID"}
FORBIDDEN_SECRET_KEYS = {"password", "passwd", "token", "secret", "api_key", "access_token"}


def _validate_attributes(attributes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(attributes, dict):
        raise RealityError("REALITY_ATTRIBUTES_MUST_BE_OBJECT")
    lowered = {str(k).lower() for k in attributes}
    forbidden = lowered & FORBIDDEN_SECRET_KEYS
    if forbidden:
        raise RealityError("SECRET_VALUE_FORBIDDEN_IN_REALITY_REGISTRY")
    return deepcopy(attributes)


class BankRealityRegistry:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "migrations": {}, "facts": {}}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1 or not isinstance(raw.get("facts"), dict):
            raise RealityError("INVALID_REALITY_REGISTRY")
        raw.setdefault("migrations", {})
        return raw

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    @staticmethod
    def _key(kind: str, fact_id: str) -> str:
        if kind not in REALITY_KINDS:
            raise RealityError("UNSUPPORTED_REALITY_KIND")
        if not isinstance(fact_id, str) or not fact_id.strip():
            raise RealityError("INVALID_REALITY_ID")
        return f"{kind}:{fact_id.strip()}"

    def upsert(
        self,
        kind: str,
        fact_id: str,
        attributes: Dict[str, Any],
        *,
        status: str = "NEEDS_BINDING",
        source_ref: Optional[str] = None,
        verified_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = self._key(kind, fact_id)
        status = str(status).upper()
        if status not in REALITY_STATUSES:
            raise RealityError("INVALID_REALITY_STATUS")
        fact = {
            "kind": kind,
            "id": fact_id,
            "status": status,
            "attributes": _validate_attributes(attributes),
            "source_ref": source_ref,
            "verified_at": verified_at,
            "drift": {},
        }
        self._state["facts"][key] = fact
        self._save()
        return deepcopy(fact)

    def get(self, kind: str, fact_id: str) -> Optional[Dict[str, Any]]:
        fact = self._state["facts"].get(self._key(kind, fact_id))
        return deepcopy(fact) if fact is not None else None

    def require(self, kind: str, fact_id: str, *, status: str = "READY") -> Dict[str, Any]:
        fact = self.get(kind, fact_id)
        if fact is None:
            raise RealityError(f"REALITY_FACT_MISSING:{kind}:{fact_id}")
        if fact["status"] != status:
            raise RealityError(f"REALITY_FACT_NOT_{status}:{kind}:{fact_id}:{fact['status']}")
        return fact

    def list(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = []
        for key in sorted(self._state["facts"]):
            fact = self._state["facts"][key]
            if kind is None or fact["kind"] == kind:
                rows.append(deepcopy(fact))
        return rows

    def migrate_once(self, source_id: str, facts: Iterable[Dict[str, Any]]) -> int:
        if not isinstance(source_id, str) or not source_id.strip():
            raise RealityError("INVALID_MIGRATION_SOURCE")
        if source_id in self._state["migrations"]:
            return 0
        staged = list(facts)
        for item in staged:
            if not isinstance(item, dict):
                raise RealityError("INVALID_MIGRATION_FACT")
            self._key(item.get("kind"), item.get("id"))
            _validate_attributes(item.get("attributes"))
            if str(item.get("status", "NEEDS_BINDING")).upper() not in REALITY_STATUSES:
                raise RealityError("INVALID_REALITY_STATUS")
        for item in staged:
            key = self._key(item["kind"], item["id"])
            self._state["facts"][key] = {
                "kind": item["kind"],
                "id": item["id"],
                "status": str(item.get("status", "NEEDS_BINDING")).upper(),
                "attributes": deepcopy(item["attributes"]),
                "source_ref": item.get("source_ref") or f"migration://{source_id}",
                "verified_at": item.get("verified_at"),
                "drift": {},
            }
        self._state["migrations"][source_id] = {"fact_count": len(staged)}
        self._save()
        return len(staged)

    def reconcile(
        self,
        kind: str,
        fact_id: str,
        observed_attributes: Dict[str, Any],
        *,
        verified_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = self._key(kind, fact_id)
        fact = self._state["facts"].get(key)
        if fact is None:
            raise RealityError("REALITY_FACT_MISSING")
        observed = _validate_attributes(observed_attributes)
        if not observed:
            fact["status"] = "NEEDS_BINDING"
            fact["drift"] = {"reason": "NO_OBSERVATION"}
        else:
            drift = {}
            canonical = fact["attributes"]
            for name, actual in observed.items():
                expected = canonical.get(name)
                if expected != actual:
                    drift[name] = {"expected": expected, "observed": actual}
            fact["drift"] = drift
            fact["status"] = "STALE" if drift else "READY"
        fact["verified_at"] = verified_at
        self._save()
        return deepcopy(fact)

    def migration_complete(self, source_id: str) -> bool:
        return source_id in self._state["migrations"]
