"""Byte-level PNG integrity gate for C09 BrowserSkill Evidence.

BrowserSkill CLI returns an image path and byte_size; neither one proves
actual valid PNG bytes. Validate structure and all per-chunk CRCs before R1.
Uses Python 3.8 stdlib only; never decodes or modifies the screenshot.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path
from typing import Dict

from .models import ContractError

_SIG = b"\x89PNG\r\n\x1a\n"
_MAX = 128 * 1024 * 1024


def verify_png_file(source: Path) -> Dict[str, object]:
    path = Path(source)
    if not path.is_file():
        raise ContractError("JOURNEY_BSK_SCREENSHOT_FILE_MISSING")
    size = path.stat().st_size
    if not 57 <= size <= _MAX:
        raise ContractError("JOURNEY_BSK_SCREENSHOT_SIZE_INVALID")
    digest = hashlib.sha256()
    seen = []
    width = height = 0
    with path.open("rb") as stream:
        signature = stream.read(8)
        digest.update(signature)
        if signature != _SIG:
            raise ContractError("JOURNEY_BSK_SCREENSHOT_NOT_PNG")
        remaining = size - 8
        while remaining >= 12:
            head = stream.read(8)
            digest.update(head)
            length, chunk_type = struct.unpack(">I4s", head)
            if length + 4 > remaining - 8 or length > _MAX:
                raise ContractError("JOURNEY_BSK_SCREENSHOT_CHUNK_TRUNCATED")
            if not all(65 <= c <= 90 or 97 <= c <= 122 for c in chunk_type):
                raise ContractError("JOURNEY_BSK_SCREENSHOT_CHUNK_INVALID")
            if not seen and (chunk_type != b"IHDR" or length != 13):
                raise ContractError("JOURNEY_BSK_SCREENSHOT_IHDR_REQUIRED")
            crc = zlib.crc32(chunk_type)
            consumed = 0
            first_payload = b""
            while consumed < length:
                data = stream.read(min(64 * 1024, length - consumed))
                if not data:
                    raise ContractError("JOURNEY_BSK_SCREENSHOT_CHUNK_TRUNCATED")
                digest.update(data)
                crc = zlib.crc32(data, crc)
                if chunk_type == b"IHDR":
                    first_payload += data
                consumed += len(data)
            stored_bytes = stream.read(4)
            if len(stored_bytes) != 4:
                raise ContractError("JOURNEY_BSK_SCREENSHOT_CHUNK_TRUNCATED")
            digest.update(stored_bytes)
            stored = struct.unpack(">I", stored_bytes)[0]
            if stored != crc & 0xFFFFFFFF:
                raise ContractError("JOURNEY_BSK_SCREENSHOT_CRC_MISMATCH")
            remaining -= length + 12
            if chunk_type == b"IHDR":
                width, height = struct.unpack(">II", first_payload[:8])
                if width == 0 or height == 0 or width > 100000 or height > 100000:
                    raise ContractError("JOURNEY_BSK_SCREENSHOT_DIMENSIONS_INVALID")
            seen.append(chunk_type)
            if chunk_type == b"IEND":
                if length != 0 or remaining != 0 or b"IDAT" not in seen:
                    raise ContractError("JOURNEY_BSK_SCREENSHOT_IEND_INVALID")
                return {"sha256": digest.hexdigest(), "bytes": size,
                        "width": width, "height": height}
        raise ContractError("JOURNEY_BSK_SCREENSHOT_IEND_MISSING")
