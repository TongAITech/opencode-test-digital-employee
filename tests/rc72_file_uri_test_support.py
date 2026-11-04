"""Strict filesystem evidence URI reader for real cross-platform RC7.2 tests.

On Windows slicing file URI produces invalid \\C: path from file:///C:/... .
Decode using platform-native URL decoder, reject remote or rewritten refs.
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
