"""tests/test_fetch_js.py — fetch_js session machinery + dispatch (no browser)."""
from __future__ import annotations

import requests

from mcp_agent_docparser import fetch as fetch_mod


def _html_response(body: bytes) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp._content = body
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


def test_close_js_session_noop_without_session():
    # nothing started on this thread — must be a silent no-op
    fetch_mod.close_js_session()


def test_shutdown_empty_registry_noop():
    before = set(fetch_mod._JS_SESSIONS)
    fetch_mod._shutdown_js_sessions()
    assert set(fetch_mod._JS_SESSIONS) == before


def test_static_dispatch_does_not_start_js_session(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return _html_response(b"<html><body><p>ok</p></body></html>")

    baseline = set(fetch_mod._JS_SESSIONS)
    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    soup = fetch_mod.fetch("http://ex.com/x", js_render=False)
    assert soup is not None
    assert "ok" in soup.get_text()
    # A static fetch must never launch Chromium / register a session.
    assert set(fetch_mod._JS_SESSIONS) == baseline


def test_fallback_selector_lists_are_populated():
    assert len(fetch_mod._COPY_MD_SELECTORS) >= 6
    assert len(fetch_mod._DOM_FALLBACK_SELECTORS) >= 5
    assert fetch_mod._DEFAULT_JS_SETTLE_MS > 0


def test_copy_page_selector_present():
    # Mintlify/Nextra themes label the copy-as-markdown widget "Copy page".
    assert "button:has-text('Copy page')" in fetch_mod._COPY_MD_SELECTORS


def test_source_clipboard_is_rejected():
    reject = fetch_mod._reject_source_clipboard
    assert reject("") is True
    assert reject("   \n\t ") is True
    # YAML frontmatter = raw source written to clipboard (Nextra "Copy page").
    assert reject("---\nasIndexPage: true\n---\n\n# Advanced") is True
    # ESM import block = raw source (MDX/MD files).
    assert reject("import { CloudIcon } from '@components/icons'\n\n# Title") is True
    # Rendered Markdown must never be rejected.
    assert reject("# Python SDK\n\nRun `pip install memvid-sdk`.") is False
    assert reject("## Installation\n\n```python\npip install memvid-sdk\n```") is False
