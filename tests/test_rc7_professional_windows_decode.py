from __future__ import annotations

from rc7_release.professional_tools import _decode_tool_bytes


def test_professional_tool_decoder_survives_mixed_windows_output() -> None:
    raw = b"codegraph-prefix\x94\xff-suffix"
    text = _decode_tool_bytes(raw)
    assert isinstance(text, str)
    assert "codegraph-prefix" in text
    assert "suffix" in text
