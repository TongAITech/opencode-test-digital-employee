from __future__ import annotations

import html
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import zlib
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .common import AI_ROOT, new_id, now_iso, safe_id, sha256_file
from .storage import jdump, one, upsert


def _fetch(source_ref: str, destination: Path, allowed_hosts: list[str] | None = None) -> None:
    parsed = urllib.parse.urlparse(source_ref)
    if parsed.scheme in {"http", "https"}:
        if allowed_hosts and parsed.hostname not in allowed_hosts:
            raise PermissionError(f"artifact host not allowed: {parsed.hostname}")
        req = urllib.request.Request(source_ref, headers={"User-Agent": "AI-Test-Artifact-Service/1.11"})
        with urllib.request.urlopen(req, timeout=60) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out)
    else:
        source = Path(source_ref).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    texts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
        elif node.tag.endswith("}p"):
            texts.append("\n")
    return "".join(texts).replace("\n\n\n", "\n\n").strip()


def _pdf_literal(text: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(text):
        b = text[i]
        if b == 92 and i + 1 < len(text):  # backslash
            i += 1
            nxt = text[i]
            mapping = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12, 40: 40, 41: 41, 92: 92}
            if nxt in mapping:
                out.append(mapping[nxt])
            elif 48 <= nxt <= 55:
                octal = bytes([nxt])
                for _ in range(2):
                    if i + 1 < len(text) and 48 <= text[i + 1] <= 55:
                        i += 1
                        octal += bytes([text[i]])
                out.append(int(octal, 8))
            else:
                out.append(nxt)
        else:
            out.append(b)
        i += 1
    for enc in ("utf-8", "utf-16-be", "latin-1"):
        try:
            return out.decode(enc)
        except UnicodeDecodeError:
            continue
    return out.decode("latin-1", errors="replace")


def _minimal_pdf_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    chunks: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        stream = m.group(1)
        try:
            stream = zlib.decompress(stream)
        except zlib.error:
            pass
        chunks.append(stream)
    chunks.append(data)
    texts: list[str] = []
    for chunk in chunks:
        for block in re.findall(rb"BT(.*?)ET", chunk, re.S):
            for literal in re.findall(rb"\((?:\\.|[^\\)])*\)", block):
                texts.append(_pdf_literal(literal[1:-1]))
            for array in re.findall(rb"\[(.*?)\]\s*TJ", block, re.S):
                for literal in re.findall(rb"\((?:\\.|[^\\)])*\)", array):
                    texts.append(_pdf_literal(literal[1:-1]))
    text = " ".join(t.strip() for t in texts if t.strip())
    if text:
        return text, "MINIMAL_PDF_PARSER"
    return "", "NEEDS_OCR_OR_EXTERNAL_PDFTOTEXT"


def extract_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx_text(path), "DOCX_XML"
    if suffix in {".txt", ".md", ".json", ".yaml", ".yml", ".csv"}:
        return path.read_text(encoding="utf-8", errors="replace"), "TEXT"
    if suffix == ".pdf":
        # Prefer an approved pdftotext binary if present, otherwise use the built-in conservative parser.
        approved = AI_ROOT / "local" / "adapters" / "pdftotext.exe"
        if approved.exists():
            target = path.with_suffix(".pdftotext.txt")
            cp = subprocess.run([str(approved), "-layout", str(path), str(target)], capture_output=True, text=True, timeout=120, check=False)
            if cp.returncode == 0 and target.exists():
                return target.read_text(encoding="utf-8", errors="replace"), "PDFTOTEXT"
        return _minimal_pdf_text(path)
    raise ValueError(f"unsupported artifact type: {suffix}")


def fetch_artifact(
    project_id: str,
    kind: str,
    source_ref: str,
    *,
    release_id: str | None = None,
    requirement_id: str | None = None,
    sst_id: str | None = None,
    allowed_hosts: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_id = new_id("ART")
    suffix = Path(urllib.parse.urlparse(source_ref).path).suffix or ".bin"
    cache = AI_ROOT / "artifacts" / "cache" / f"{artifact_id}-{safe_id(kind)}{suffix}"
    cache.parent.mkdir(parents=True, exist_ok=True)
    _fetch(source_ref, cache, allowed_hosts)
    digest = sha256_file(cache)
    text_path = cache.with_suffix(cache.suffix + ".txt")
    try:
        text, parser = extract_text(cache)
        text_path.write_text(text, encoding="utf-8")
        parse_status = "PARSED" if text else parser
        parsed_at = now_iso()
    except Exception as exc:
        text_path = None
        parser = "ERROR"
        parse_status = f"PARSE_ERROR:{type(exc).__name__}"
        parsed_at = now_iso()
    record = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "release_id": release_id,
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "kind": kind,
        "source_ref": source_ref,
        "cache_path": str(cache),
        "sha256": digest,
        "media_type": suffix.lower(),
        "parse_status": parse_status,
        "text_path": str(text_path) if text_path else None,
        "fetched_at": now_iso(),
        "parsed_at": parsed_at,
        "metadata_json": jdump({**(metadata or {}), "parser": parser}),
    }
    upsert("artifacts", ["artifact_id"], record)
    return {**record, "metadata": {**(metadata or {}), "parser": parser}}


def artifact_status(artifact_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,))
    if not row:
        raise KeyError(artifact_id)
    return row
