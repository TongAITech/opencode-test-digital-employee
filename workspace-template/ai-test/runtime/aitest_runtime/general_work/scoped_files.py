"""Trusted bounded file broker, separate from the OS sandbox for arbitrary code.

POSIX walks use no-follow directory descriptors. Windows holds every directory
without delete sharing and rejects reparse points, including junctions. Final
files must be regular, single-link files. Model paths never become shell input.
"""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
import difflib
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
import uuid

from aitest_runtime.durable_core import RuntimeError
from aitest_runtime.r2_1.contracts import validate_secret_boundary
from .execution_contract import require

PROTECTED = frozenset({".git", ".opencode", ".codex", ".agents", ".ssh", ".aws", ".azure",
    "state", "evidence", "auth", "secrets", "browser-profile", "browser-profiles", "general-results",
    "general-backups", "governance", "frozen-cases", "receipts", "node_modules", "__pycache__"})
SENSITIVE_SUFFIX = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12", ".der"}
MAX_FILE = 4 * 1024 * 1024
PROTECTED_WRITE_ROOTS = {"runtime", "ai-test", "data", "bindings", "tools", "tests", "projects", "repositories", "repos"}
PROTECTED_WRITE_FILES = {"agents.md", "opencode.json", "opencode.jsonc", "install_manifest.json", "runtime-lock.json", "package_manifest.json", "offline_payload_registry.json", "aitest.sh", "install.sh"}


def sha(data): return hashlib.sha256(data).hexdigest()


def exchange(parent, fd, left, right):
    """Swap two existing directory entries atomically, preserving both versions.

    The displaced bytes are inspected after the atomic operation. An expected
    hash is not represented as universal filesystem CAS against arbitrary apps.
    """
    import ctypes
    require(os.name != "nt", "GENERAL_ATOMIC_EXCHANGE_BACKEND_REQUIRED")
    libc = ctypes.CDLL(None, use_errno=True)
    name = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    fn = getattr(libc, name, None)
    require(fn is not None, "GENERAL_ATOMIC_EXCHANGE_BACKEND_REQUIRED")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(fd, os.fsencode(left), fd, os.fsencode(right), 2) != 0:
        raise OSError(ctypes.get_errno(), "atomic file exchange failed")


def safe_text(data):
    text = data.decode("utf-8", errors="replace")
    try:
        validate_secret_boundary({"file_content": text})
    except Exception:
        return "[Content withheld by the credential boundary]", True
    return text, False


@contextmanager
def windows_guard(path, *, directory):
    """Prevent component substitution while a trusted broker operation runs."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    # Attribute access only; no FILE_SHARE_DELETE. For regular files also deny writes.
    flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT, BACKUP_SEMANTICS
    handle = kernel.CreateFileW(str(path), 0x80, 3 if directory else 1, None, 3, flags, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot hold a scope component")
    try:
        attrs = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attrs), ctypes.sizeof(attrs)):
            raise OSError(ctypes.get_last_error(), "cannot verify file attributes")
        require(not (attrs[0] & 0x400), "GENERAL_REPARSE_POINT_DENIED")
        require(bool(attrs[0] & 0x10) == directory, "GENERAL_FILE_TYPE_DENIED")
        yield handle
    finally:
        kernel.CloseHandle(handle)


class ScopedFiles:
    def __init__(self, workspace_root, write_roots, private_root, write_paths=()):
        self.root = Path(workspace_root).resolve(strict=True)
        self.write_roots = tuple(PurePosixPath(p) for p in write_roots)
        self.private = Path(private_root)
        self.write_paths = frozenset(write_paths)
        self.sealed_paths = set()
        manifest = self.root / "INSTALL_MANIFEST.json"
        if manifest.is_file():
            require(not manifest.is_symlink() and manifest.stat().st_size <= 8 * 1024 * 1024, "GENERAL_INSTALL_MANIFEST_INVALID")
            value = json.loads(manifest.read_text(encoding="utf-8"))
            # Source/install inventories use mappings or rows; conservatively
            # protect every path they mention, without making manifest contents
            # an authority to grant additional access.
            def collect(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, str) and "/" in k: self.sealed_paths.add(k.casefold())
                        if k in {"path", "relative_path"} and isinstance(v, str): self.sealed_paths.add(v.casefold())
                        collect(v)
                elif isinstance(obj, list):
                    for v in obj: collect(v)
            collect(value)

    def relative(self, value, *, write=False, allow_root=False):
        require(isinstance(value, str) and 0 < len(value.encode()) <= 2048, "GENERAL_PATH_INVALID")
        # One unambiguous portable syntax: no UNC/device/ADS/backslash, trailing dot,
        # reserved DOS alias, or encoded traversal hidden in platform normalization.
        require("\\" not in value and "\x00" not in value and ":" not in value, "GENERAL_PATH_SYNTAX_DENIED")
        p = Path(value)
        if p.is_absolute():
            try: value = p.relative_to(self.root).as_posix()
            except ValueError: raise RuntimeError("GENERAL_PATH_OUTSIDE_SCOPE", "path is outside the workspace") from None
        parts = PurePosixPath(value).parts
        require(not any(x in {"..", "/"} or x.endswith((".", " ")) or re.match(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", x) for x in parts), "GENERAL_PATH_SYNTAX_DENIED")
        if not parts:
            require(allow_root and not write, "GENERAL_FILE_PATH_REQUIRED")
            return PurePosixPath(".")
        require(not any(x.casefold() in PROTECTED or x.casefold().startswith((".env", ".aitest-")) for x in parts), "GENERAL_PROTECTED_OBJECT_DENIED")
        require(PurePosixPath(*parts).suffix.casefold() not in SENSITIVE_SUFFIX, "GENERAL_PROTECTED_OBJECT_DENIED")
        rel = PurePosixPath(*parts)
        if parts[0].casefold() == "general-work":
            require(any(rel.is_relative_to(r) for r in self.write_roots if r.parts[0] == "general-work"), "GENERAL_OTHER_JOB_RESOURCE_DENIED")
        if write:
            require(parts[0].casefold() not in PROTECTED_WRITE_ROOTS and rel.as_posix().casefold() not in PROTECTED_WRITE_FILES and rel.as_posix().casefold() not in self.sealed_paths, "GENERAL_PROTECTED_OBJECT_DENIED")
            require(rel.as_posix() in self.write_paths or any(rel.is_relative_to(r) and rel != r for r in self.write_roots), "GENERAL_WRITE_SCOPE_DENIED")
        return rel

    @contextmanager
    def parent(self, rel, *, create=False):
        with ExitStack() as stack:
            if os.name == "nt":
                p = Path(self.root.anchor)
                stack.enter_context(windows_guard(p, directory=True))
                for component in self.root.parts[1:]:
                    p /= component
                    stack.enter_context(windows_guard(p, directory=True))
                for component in rel.parts[:-1]:
                    p /= component
                    if create:
                        try: p.mkdir(mode=0o700)
                        except FileExistsError: pass
                    stack.enter_context(windows_guard(p, directory=True))
                yield p, None
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(str(self.root), flags)
                stack.callback(os.close, fd)
                for component in rel.parts[:-1]:
                    if create:
                        try: os.mkdir(component, 0o700, dir_fd=fd)
                        except FileExistsError: pass
                    next_fd = os.open(component, flags, dir_fd=fd)
                    stack.callback(os.close, next_fd)
                    fd = next_fd
                yield self.root.joinpath(*rel.parts[:-1]), fd

    @contextmanager
    def opened(self, parent, fd, name):
        with ExitStack() as stack:
            if os.name == "nt":
                stack.enter_context(windows_guard(parent / name, directory=False))
                fileno = os.open(parent / name, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
            else:
                fileno = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            stack.callback(os.close, fileno)
            s = os.fstat(fileno)
            require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "GENERAL_FILE_TYPE_OR_HARDLINK_DENIED")
            require(s.st_size <= MAX_FILE, "GENERAL_FILE_BYTE_BUDGET")
            yield fileno, s

    def _whole(self, parent, fd, name):
        try:
            with self.opened(parent, fd, name) as (fileno, original):
                chunks, total = [], 0
                while True:
                    chunk = os.read(fileno, min(65536, MAX_FILE + 1 - total))
                    if not chunk: break
                    chunks.append(chunk); total += len(chunk)
                    require(total <= MAX_FILE, "GENERAL_FILE_BYTE_BUDGET")
                latest = os.fstat(fileno)
                require((original.st_ino, original.st_size, original.st_mtime_ns) == (latest.st_ino, latest.st_size, latest.st_mtime_ns), "GENERAL_FILE_CHANGED_DURING_READ")
                return b"".join(chunks), original
        except FileNotFoundError:
            return None, None

    def read(self, path, offset=0, limit=8192):
        require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 16384, "GENERAL_READ_BUDGET_INVALID")
        rel = self.relative(path)
        with self.parent(rel) as (parent, fd):
            data, _ = self._whole(parent, fd, rel.name)
        require(data is not None, "GENERAL_FILE_NOT_FOUND")
        text, redacted = safe_text(data[offset:offset + limit])
        # Check the complete bounded file too: slicing must not evade secret detection.
        _, whole_redacted = safe_text(data)
        if whole_redacted: text, redacted = "[Content withheld by the credential boundary]", True
        return {"path": rel.as_posix(), "sha256": sha(data), "bytes": len(data), "offset": offset,
                "next_offset": min(offset + limit, len(data)), "truncated": offset + limit < len(data), "content": text, "redacted": redacted}

    def write(self, path, expected_sha256, content, call_key):
        require(isinstance(content, str) and len(content.encode()) <= 65536, "GENERAL_WRITE_BYTE_BUDGET")
        validate_secret_boundary({"content": content})
        require(expected_sha256 == "MISSING" or isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "GENERAL_EXPECTED_DIGEST_REQUIRED")
        rel = self.relative(path, write=True); data = content.encode()
        with self.parent(rel, create=True) as (parent, fd):
            before, st = self._whole(parent, fd, rel.name)
            before_sha = sha(before) if before is not None else "MISSING"
            require(before_sha == expected_sha256, "GENERAL_WRITE_CONFLICT")
            backup = self.private / "general-backups" / call_key
            backup.mkdir(parents=True, exist_ok=False, mode=0o700)
            if before is not None:
                _private_write(backup / "before.bin", before)
            diff = "".join(difflib.unified_diff((before or b"").decode("utf-8", "replace").splitlines(True), content.splitlines(True), fromfile=rel.as_posix(), tofile=rel.as_posix()))
            _private_write(backup / "change.diff", diff.encode())
            tmp = ".aitest-" + uuid.uuid4().hex + ".tmp"
            _private_write(backup / "transaction.json", json.dumps({"path": rel.as_posix(), "temporary_name": tmp,
                "before_sha256": before_sha, "after_sha256": sha(data), "call_key": call_key}).encode())
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            temp_fd = os.open(parent / tmp if fd is None else tmp, flags, 0o600, **({"dir_fd": fd} if fd is not None else {}))
            preserve_displaced = False
            try:
                with os.fdopen(temp_fd, "wb") as f:
                    f.write(data); f.flush(); os.fsync(f.fileno())
                latest, latest_st = self._whole(parent, fd, rel.name)
                require((sha(latest) if latest is not None else "MISSING") == before_sha and (st is None or latest_st is not None and (st.st_ino, st.st_dev) == (latest_st.st_ino, latest_st.st_dev)), "GENERAL_WRITE_CONFLICT")
                if before is None:
                    # Exclusive installation preserves a racing creator.
                    if fd is None: os.link(parent / tmp, parent / rel.name)
                    else: os.link(tmp, rel.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                elif fd is None:
                    self._windows_replace(parent, tmp, rel.name, before_sha, backup)
                else:
                    exchange(parent, fd, tmp, rel.name)
                    preserve_displaced = True
                    try: displaced, _ = self._whole(parent, fd, tmp)
                    except Exception as exc:
                        # Unknown displaced content must survive even if it is
                        # oversized, linked, unreadable or otherwise invalid.
                        installed, _ = self._whole(parent, fd, rel.name)
                        if installed == data:
                            exchange(parent, fd, tmp, rel.name)
                            moved, _ = self._whole(parent, fd, tmp)
                            if moved == data:
                                preserve_displaced = False
                                raise RuntimeError("GENERAL_WRITE_CONFLICT", "concurrent file restored without reading its full body") from exc
                        raise RuntimeError("GENERAL_WRITE_RECONCILIATION_REQUIRED", "unverified displaced file retained") from exc
                    if sha(displaced) != before_sha:
                        _private_write(backup / "concurrent-edit.bin", displaced)
                        # Keep the displaced concurrent edit; restore only while
                        # our installed version remains current. A second writer
                        # is preserved separately instead of discarded.
                        installed, _ = self._whole(parent, fd, rel.name)
                        if installed == data:
                            exchange(parent, fd, tmp, rel.name)
                            displaced_again, _ = self._whole(parent, fd, tmp)
                            if displaced_again != data:
                                _private_write(backup / "second-concurrent-edit.bin", displaced_again)
                        preserve_displaced = False
                        raise RuntimeError("GENERAL_WRITE_CONFLICT", "concurrent content preserved in backup")
                    preserve_displaced = False
                    os.fsync(fd)
            finally:
                try:
                    if not preserve_displaced:
                        if fd is None: (parent / tmp).unlink()
                        else: os.unlink(tmp, dir_fd=fd)
                except FileNotFoundError: pass
        return {"path": rel.as_posix(), "before_sha256": before_sha, "sha256": sha(data), "bytes": len(data),
                "backup_ref": "general-backups/" + call_key, "diff_sha256": sha(diff.encode())}

    def _windows_replace(self, parent, tmp, target, expected, backup):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = kernel.ReplaceFileW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        fn.restype = wintypes.BOOL
        displaced = parent / (tmp + ".displaced")
        if not fn(str(parent / target), str(parent / tmp), str(displaced), 0, None, None):
            raise OSError(ctypes.get_last_error(), "atomic ReplaceFile failed")
        old, _ = self._whole(parent, None, displaced.name)
        try:
            if sha(old) != expected:
                _private_write(backup / "concurrent-edit.bin", old)
                second = parent / (tmp + ".second")
                if not fn(str(parent / target), str(displaced), str(second), 0, None, None):
                    raise RuntimeError("GENERAL_WRITE_CONFLICT", "concurrent content preserved in backup; restore conflicted")
                current, _ = self._whole(parent, None, second.name)
                _private_write(backup / "displaced-during-restore.bin", current)
                second.unlink()
                raise RuntimeError("GENERAL_WRITE_CONFLICT", "concurrent content restored and preserved")
        finally:
            if displaced.exists(): displaced.unlink()

    def search(self, path, pattern, glob="*", offset=0, limit=20):
        require(isinstance(pattern, str) and 0 < len(pattern.encode()) <= 1024 and isinstance(glob, str) and 0 < len(glob) <= 128, "GENERAL_SEARCH_PATTERN_INVALID")
        require(type(offset) is int and 0 <= offset <= 4096 and type(limit) is int and 1 <= limit <= 50, "GENERAL_SEARCH_BUDGET_INVALID")
        rel = self.relative(path, allow_root=True)
        candidates, pending, visited = [], [rel], 0
        deadline = time.monotonic() + 2
        while pending and visited < 4096 and time.monotonic() < deadline:
            folder = pending.pop(0)
            # A sentinel makes parent() hold the folder itself before listing.
            try:
                with self.parent(folder / ".listing") as (actual, dir_fd):
                    with os.scandir(actual if dir_fd is None else dir_fd) as iterator:
                        for item in iterator:
                            visited += 1
                            if visited > 4096 or time.monotonic() >= deadline: break
                            child = folder / item.name
                            try: self.relative(child.as_posix(), allow_root=True)
                            except RuntimeError: continue
                            if item.is_symlink(): continue
                            if item.is_dir(follow_symlinks=False): pending.append(child)
                            elif item.is_file(follow_symlinks=False) and fnmatch.fnmatchcase(item.name, glob): candidates.append(child.as_posix())
            except OSError:
                if folder == rel: raise
                continue
        candidates.sort()
        matches, errors, cursor = [], 0, offset
        for candidate in candidates[offset:]:
            if len(matches) >= limit: break
            cursor += 1
            try:
                row = self.read(candidate, 0, 16384)
                if row["redacted"]: continue
                if pattern in row["content"]:
                    matches.append({"path": candidate, "sha256": row["sha256"], "sample": row["content"][max(0, row["content"].index(pattern) - 80):][:512], "file_sample_truncated": row["truncated"]})
            except (RuntimeError, OSError): errors += 1
        return {"matches": matches, "next_offset": cursor, "candidate_limit_reached": bool(pending) or visited >= 4096 or time.monotonic() >= deadline,
                "visited_entries": visited, "enumeration_budget": 4096,
                "truncated": cursor < len(candidates), "files_skipped": errors, "search_scope": "first 16384 bytes per eligible file"}


def _private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
