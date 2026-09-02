from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError

REDACTED = "[REDACTED:SENSITIVE]"

_CHANNEL_CLASS = {
    "authorization": "AUTHORIZATION",
    "proxyauthorization": "AUTHORIZATION",
    "cookie": "COOKIE",
    "setcookie": "COOKIE",
    "accesstoken": "TOKEN",
    "refreshtoken": "TOKEN",
    "token": "TOKEN",
    "sessionid": "SESSION",
    "jsessionid": "SESSION",
    "password": "PASSWORD",
    "passwd": "PASSWORD",
    "pwd": "PASSWORD",
    "otp": "OTP",
    "captcha": "CAPTCHA",
    "captcharesponse": "CAPTCHA",
}

_DEFENSE_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|pwd|otp|captcha|access[_-]?token|refresh[_-]?token|authorization|cookie|session[_-]?id|jsessionid)\s*[:=]\s*[^\s,;&]+"),
    re.compile(r"(?i)^Bearer\s+\S+$"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
)


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _channel(key: str) -> str | None:
    normalized = _norm(key)
    direct = _CHANNEL_CLASS.get(normalized)
    if direct:
        return direct
    for sensitive, classification in _CHANNEL_CLASS.items():
        if normalized.endswith(sensitive) or normalized.startswith(sensitive):
            return classification
    return None


@dataclass(frozen=True)
class EvidenceSanitization:
    value: Any
    classifications: tuple[str, ...]
    redaction_count: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "sensitive_value_policy": "TYPED_INGRESS_REDACTION_V1",
            "classifications": list(self.classifications),
            "redaction_count": self.redaction_count,
            "raw_sensitive_value_persisted": False,
        }


def sanitize_evidence_ingress(
    value: Any,
    *,
    path: str = "evidence",
    sensitive_entry_mode: bool = False,
) -> EvidenceSanitization:
    classifications: set[str] = set()
    redactions = 0

    def walk(item: Any, current_path: str, forced_class: str | None = None) -> Any:
        nonlocal redactions
        if forced_class is not None:
            classifications.add(forced_class)
            redactions += 1
            return REDACTED
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, (int, float)):
            if sensitive_entry_mode:
                classifications.add("SENSITIVE_ENTRY")
                redactions += 1
                return REDACTED
            return item
        if isinstance(item, str):
            if sensitive_entry_mode:
                classifications.add("SENSITIVE_ENTRY")
                redactions += 1
                return REDACTED
            if any(pattern.search(item) for pattern in _DEFENSE_PATTERNS):
                classifications.add("DEFENSE_IN_DEPTH_PATTERN")
                redactions += 1
                return REDACTED
            return item
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise RuntimeError("G4_SCHEMA_INVALID", f"{current_path} object keys must be strings")
                classification = _channel(key)
                result[key] = walk(child, f"{current_path}.{key}", classification)
            return result
        if isinstance(item, (list, tuple)):
            return [walk(child, f"{current_path}[]") for child in item]
        if isinstance(item, Enum):
            return item.value
        raise RuntimeError("G4_SCHEMA_INVALID", f"{current_path} must contain canonical JSON values")

    sanitized = walk(value, path)
    return EvidenceSanitization(sanitized, tuple(sorted(classifications)), redactions)
