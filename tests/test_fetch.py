"""tests/test_fetch.py — fetch-layer decoding and error handling (no network)."""
from __future__ import annotations

import re

import pytest
import requests


def _make_response(content: bytes, declared: str | None) -> requests.Response:
    """Build a real requests.Response whose headers declare (or omit) a charset."""
    resp = requests.Response()
    resp._content = content
    resp.encoding = declared or "ISO-8859-1"
    headers = {"Content-Type": "text/html"}
    if declared:
        headers["Content-Type"] = f"text/html; charset={declared}"
    resp.headers.update(headers)
    return resp


@pytest.fixture
def utf8_page_bytes() -> bytes:
    return (
        "<html><body><h1>Norwegian Bokmål</h1>"
        "<p>YouTube’s player — café</p></body></html>"
    ).encode()


class TestDecode:
    def test_utf8_declared_is_honoured(self, utf8_page_bytes):
        from mcp_agent_docparser.fetch import _decode_body

        body = _decode_body(_make_response(utf8_page_bytes, "utf-8"))
        assert "Bokmål" in body
        assert "YouTube’s" in body

    def test_missing_charset_falls_back_to_utf8(self, utf8_page_bytes):
        """requests defaults to latin-1 with no charset — we must prefer UTF-8."""
        from mcp_agent_docparser.fetch import _decode_body

        body = _decode_body(_make_response(utf8_page_bytes, None))
        assert "Bokmål" in body
        assert "YouTube’s" in body
        assert "café" in body
        assert "â" not in body

    def test_latin1_declared_is_honoured(self):
        from mcp_agent_docparser.fetch import _decode_body

        content = "<p>café</p>".encode("iso-8859-1")
        body = _decode_body(_make_response(content, "iso-8859-1"))
        assert "café" in body

    def test_broken_utf8_with_iso_declared_does_not_raise(self):
        from mcp_agent_docparser.fetch import _decode_body

        content = b"<p>t\xe9xt</p>"  # latin-1 bytes under an utf-8 declaration
        body = _decode_body(_make_response(content, "utf-8"))
        assert re.fullmatch(r"<p>t.xt</p>", body)  # errors="replace", no exception
