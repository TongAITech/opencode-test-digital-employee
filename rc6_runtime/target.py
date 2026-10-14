"""Fail-closed execution TargetIdentity for RC6 Wave 3."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Dict

from .reality import BankRealityRegistry, RealityError


class TargetIdentityError(RuntimeError):
    pass


REQUIRED_REPOSITORIES = ("cfg-admin", "cfg-data", "cfg-scd", "cfg-center")
REQUIRED_DATABASE_APPS = ("cfg-data", "cfg-scd", "cfg-center")
DEPLOYMENT_MODES = {"REMOTE_DEPLOYMENT", "LOCAL_BUILD"}


@dataclass(frozen=True)
class TargetIdentity:
    target_id: str
    release_id: str
    deployment_mode: str
    environment_id: str
    repositories: Dict[str, str]
    frontend_url: str
    api_gateway_url: str
    databases: Dict[str, str]
    auth_profile: str
    cat_profile: str
    account_profile: str

    def as_dict(self):
        return asdict(self)


class TargetIdentityBuilder:
    def __init__(self, registry: BankRealityRegistry):
        self.registry = registry

    def _ready(self, kind: str, fact_id: str):
        try:
            return self.registry.require(kind, fact_id, status="READY")
        except RealityError as exc:
            raise TargetIdentityError(str(exc)) from exc

    def build(
        self,
        *,
        release_id: str,
        deployment_mode: str,
        environment_fact_id: str,
        repository_fact_ids: Dict[str, str],
        frontend_route_fact_id: str,
        gateway_route_fact_id: str,
        database_fact_ids: Dict[str, str],
        auth_fact_id: str,
        cat_fact_id: str,
        account_fact_id: str,
    ) -> TargetIdentity:
        if deployment_mode not in DEPLOYMENT_MODES:
            raise TargetIdentityError("INVALID_DEPLOYMENT_MODE")
        if not isinstance(release_id, str) or not release_id.strip():
            raise TargetIdentityError("INVALID_RELEASE_ID")

        missing_repos = [x for x in REQUIRED_REPOSITORIES if x not in repository_fact_ids]
        if missing_repos:
            raise TargetIdentityError("TARGET_REPOSITORY_BINDING_INCOMPLETE")
        missing_dbs = [x for x in REQUIRED_DATABASE_APPS if x not in database_fact_ids]
        if missing_dbs:
            raise TargetIdentityError("TARGET_DATABASE_BINDING_INCOMPLETE")

        env = self._ready("environment", environment_fact_id)
        env_attrs = env["attributes"]
        deployed_release = env_attrs.get("deployed_release_id")
        if deployed_release and deployed_release != release_id:
            raise TargetIdentityError("TARGET_ENVIRONMENT_RELEASE_MISMATCH")

        repositories = {}
        for app in REQUIRED_REPOSITORIES:
            fact = self._ready("repository", repository_fact_ids[app])
            attrs = fact["attributes"]
            if attrs.get("application") != app:
                raise TargetIdentityError("TARGET_REPOSITORY_APPLICATION_MISMATCH")
            if attrs.get("release_id") != release_id:
                raise TargetIdentityError("TARGET_REPOSITORY_RELEASE_MISMATCH")
            revision = attrs.get("revision")
            if not isinstance(revision, str) or not revision.strip():
                raise TargetIdentityError("TARGET_REPOSITORY_REVISION_MISSING")
            repositories[app] = revision.strip()

        frontend = self._ready("route", frontend_route_fact_id)
        gateway = self._ready("route", gateway_route_fact_id)
        for route in (frontend, gateway):
            attrs = route["attributes"]
            if attrs.get("environment_id") != environment_fact_id:
                raise TargetIdentityError("TARGET_ROUTE_ENVIRONMENT_MISMATCH")
            if not isinstance(attrs.get("url"), str) or not attrs["url"].strip():
                raise TargetIdentityError("TARGET_ROUTE_URL_MISSING")

        databases = {}
        for app in REQUIRED_DATABASE_APPS:
            fact = self._ready("database", database_fact_ids[app])
            attrs = fact["attributes"]
            if attrs.get("application") != app:
                raise TargetIdentityError("TARGET_DATABASE_APPLICATION_MISMATCH")
            if attrs.get("environment_id") != environment_fact_id:
                raise TargetIdentityError("TARGET_DATABASE_ENVIRONMENT_MISMATCH")
            profile_id = attrs.get("profile_id")
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise TargetIdentityError("TARGET_DATABASE_PROFILE_MISSING")
            databases[app] = profile_id.strip()

        auth = self._ready("auth", auth_fact_id)
        cat = self._ready("cat", cat_fact_id)
        account = self._ready("account", account_fact_id)
        for kind, fact in (("AUTH", auth), ("CAT", cat), ("ACCOUNT", account)):
            fact_env = fact["attributes"].get("environment_id")
            if fact_env and fact_env != environment_fact_id:
                raise TargetIdentityError(f"TARGET_{kind}_ENVIRONMENT_MISMATCH")

        canonical = {
            "release_id": release_id,
            "deployment_mode": deployment_mode,
            "environment_id": environment_fact_id,
            "repositories": repositories,
            "frontend_url": frontend["attributes"]["url"].strip(),
            "api_gateway_url": gateway["attributes"]["url"].strip(),
            "databases": databases,
            "auth_profile": auth_fact_id,
            "cat_profile": cat_fact_id,
            "account_profile": account_fact_id,
        }
        digest = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        return TargetIdentity(target_id=f"TARGET-{digest}", **canonical)
