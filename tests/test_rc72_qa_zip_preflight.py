"""Negative tests ensure C12 does not unpack untrusted archive entries."""
import json
import stat
import zipfile

import pytest

from tools.rc72_qa_zip_preflight import EXPECTED_ROOT, UnsafeArchiveError, inspect_zip, main


def _make(tmp_path, members):
    path = tmp_path / "real-c12-inner-transport.zip"
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    # On Windows ZipInfo normalizes literal backslashes into forward slashes
    # BEFORE writing the ZIP. Mutate ONLY the filename bytes in the two ZIP
    # headers, so this negative case exercises a real malicious ZIP entry
    # rather than Python's already-sanitized test fixture.
    for name, _ in members:
        if "\\\\" in name:
            normalized = name.replace("\\\\", "/").encode("utf-8")
            malicious = name.encode("utf-8")
            raw = path.read_bytes()
            if normalized != malicious and normalized in raw:
                assert raw.count(normalized) == 2  # local + central headers
                path.write_bytes(raw.replace(normalized, malicious))
    return path


def test_exact_root_real_archive_preflight_is_not_bank_final(tmp_path):
    archive = _make(tmp_path, [(EXPECTED_ROOT + "/SOURCE_COMMIT", "a" * 40),
                               (EXPECTED_ROOT + "/BUILD_ID", "RC7.2-" + "a" * 12)])
    result = inspect_zip(archive)
    assert result["status"] == "STRUCTURAL_PREFLIGHT_ONLY"
    assert result["file_entries"] == 2
    assert result["total_uncompressed_bytes"] == 40 + len("RC7.2-") + 12
    assert result["field_verified"] is False and result["bank_final"] is False
    receipt = tmp_path / "audit-before-extraction.json"
    assert main(["--zip", str(archive), "--report", str(receipt)]) == 0
    assert json.loads(receipt.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("path,reason", [
    ("../escape.txt", "NONCANONICAL_ARCHIVE_PATH"),
    ("/tmp/escape.txt", "UNSAFE_ARCHIVE_NAME"),
    (EXPECTED_ROOT + "/../escape.txt", "NONCANONICAL_ARCHIVE_PATH"),
    (EXPECTED_ROOT + "//payload.bin", "NONCANONICAL_ARCHIVE_PATH"),
    (EXPECTED_ROOT + "/./payload.bin", "NONCANONICAL_ARCHIVE_PATH"),
    (EXPECTED_ROOT + r"\..\escape.txt", "UNSAFE_ARCHIVE_NAME"),
    (EXPECTED_ROOT + "/payload:name", "NONCANONICAL_ARCHIVE_PATH"),
    ("FOREIGN-RELEASE/SOURCE_COMMIT", "ARCHIVE_WRONG_ROOT"),
    (EXPECTED_ROOT, "ROOT_FILE_FORBIDDEN"),
])
def test_bad_root_or_path_fails_before_archive_extraction(tmp_path, path, reason):
    archive = _make(tmp_path, [(path, b"untrusted")])
    with pytest.raises(UnsafeArchiveError, match=reason):
        inspect_zip(archive)


def test_duplicate_member_with_valid_zip_structure_still_fails(tmp_path):
    archive = _make(tmp_path, [(EXPECTED_ROOT + "/payload.dat", b"1"),
                               (EXPECTED_ROOT + "/payload.dat", b"2")])
    with pytest.raises(UnsafeArchiveError, match="DUPLICATE_ENTRY"):
        inspect_zip(archive)


def test_zip_symlink_is_never_treated_as_an_ordinary_payload(tmp_path):
    archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo(EXPECTED_ROOT + "/evil-link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(str(archive), "w") as writer:
        writer.writestr(link, "../../outside")
    with pytest.raises(UnsafeArchiveError, match="SYMLINK_FORBIDDEN"):
        inspect_zip(archive)


def test_corrupt_zip_and_existing_receipt_cannot_be_admitted(tmp_path):
    bad = tmp_path / "fake.zip"
    bad.write_bytes(b"fake-content")
    with pytest.raises(UnsafeArchiveError, match="CORRUPTED_OR_UNREADABLE"):
        inspect_zip(bad)
    archive = _make(tmp_path, [(EXPECTED_ROOT + "/SOURCE_COMMIT", "a" * 40)])
    existing = tmp_path / "existing-report.json"
    existing.write_bytes(b"immutable-report")
    assert main(["--zip", str(archive), "--report", str(existing)]) == 1
    assert existing.read_bytes() == b"immutable-report"



@pytest.mark.parametrize("first,second", [
    ("tools/Driver.exe", "tools/driver.EXE"),
    ("Browser/Profile/Session.JSON", "browser/profile/session.json"),
    ("one", "ONE"),
])
def test_ntfs_case_insensitive_collisions_rejected_before_unpack(tmp_path, first, second):
    archive = _make(tmp_path, [
        (EXPECTED_ROOT + "/" + first, b"legitimate"),
        (EXPECTED_ROOT + "/" + second, b"overwrite"),
    ])
    with pytest.raises(UnsafeArchiveError, match="WINDOWS_CASEFOLD_COLLISION"):
        inspect_zip(archive)


@pytest.mark.parametrize("unsafe", [
    "CON", "con.txt", "AuX.JSON", "NUL", "prn",
    "COM1", "com9.dll", "lpt1", "LPT9.out",
    "trailing.", "trailing ", "payload/ending.",
    "payload/ending ", "payload/control\x01char",
])
def test_ntfs_reserved_device_and_nonportable_file_names_refused(tmp_path, unsafe):
    archive = _make(tmp_path, [(EXPECTED_ROOT + "/" + unsafe, b"binary")])
    with pytest.raises(UnsafeArchiveError, match="WINDOWS_UNSAFE_ARCHIVE_PATH"):
        inspect_zip(archive)


@pytest.mark.parametrize("names", [
    ["config", "config/child.json"],
    ["browser/Runtime", "browser/runtime/chromium.bin"],
])
def test_zip_file_cannot_be_parent_of_another_path_on_windows(tmp_path, names):
    archive = _make(tmp_path, [(EXPECTED_ROOT + "/" + name, b"data") for name in names])
    with pytest.raises(UnsafeArchiveError, match="WINDOWS_FILE_DIRECTORY_COLLISION"):
        inspect_zip(archive)



@pytest.mark.parametrize("entry_name,unix_mode,reason", [
    ("device", stat.S_IFCHR | 0o600, "SPECIAL_FILE_FORBIDDEN"),
    ("fifo", stat.S_IFIFO | 0o600, "SPECIAL_FILE_FORBIDDEN"),
    ("dir-mode-on-file", stat.S_IFDIR | 0o700, "DIRECTORY_TYPE_MISMATCH"),
    ("file-mode-on-dir/", stat.S_IFREG | 0o600, "DIRECTORY_TYPE_MISMATCH"),
])
def test_unix_special_types_and_conflicting_file_directory_modes_rejected(
        tmp_path, entry_name, unix_mode, reason):
    archive = tmp_path / "unsafe-unix-mode.zip"
    entry = zipfile.ZipInfo(EXPECTED_ROOT + "/" + entry_name)
    entry.create_system = 3
    entry.external_attr = unix_mode << 16
    with zipfile.ZipFile(str(archive), "w") as writer:
        writer.writestr(entry, b"")
    with pytest.raises(UnsafeArchiveError, match=reason):
        inspect_zip(archive)
