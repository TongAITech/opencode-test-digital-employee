"""Strict filesystem evidence URI reader for real cross-platform RC7.2 tests.

On Windows Path(file_uri[7:]) produces an invalid \\C: path for standards-
compliant file:///C:/...; use urllib's platform-native URL decoder instead.
Never accept a remote, query-bearing or fragment-bearing URI as local proof.
"""
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname


def local_file_evidence_ref(uri):
    parts = urlsplit(uri)
    assert parts.scheme == "file" and parts.netloc == ""
    assert not parts.query and not parts.fragment
    candidate = Path(url2pathname(parts.path))
    assert candidate.is_absolute()
    assert candidate.resolve().as_uri() == uri
    return candidate
