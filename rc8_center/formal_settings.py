"""Formal RC8 Center settings.

The product runtime is server-side and independent from office-node Python/DSH.
Configuration is environment driven so Docker Compose and bank deployment can
supply PostgreSQL/Redis/artifact locations without changing domain code.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CenterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RC8_", case_sensitive=False, extra="ignore")

    app_name: str = "RC8 Center"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "postgresql+psycopg://rc8:rc8@postgresql:5432/rc8"
    redis_url: str = "redis://redis:6379/0"
    artifact_root: str = "/var/lib/rc8/artifacts"

    # R1 remains runtime truth; PostgreSQL stores durable domain/projection state.
    r1_root: str = "/var/lib/rc8/r1"

    def architecture(self) -> dict:
        return {
            "backend": "FastAPI",
            "api_validation": "Pydantic",
            "persistence": "PostgreSQL",
            "orm": "SQLAlchemy",
            "migration": "Alembic",
            "coordination": "Redis",
            "frontend": "Vue3+TypeScript+Vite",
            "web_edge": "Nginx",
            "deployment": "DockerCompose",
            "runtime_truth": "R1_EVENT_STREAM",
        }
