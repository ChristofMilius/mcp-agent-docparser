"""
fetch.py — Fetch layer (static + JS-rendered)
=============================================
Ported from the terminal-menu docparser. server mode routes messages through
the logging module instead of printing (stdio must stay clean).
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0 Safari/537.36"
    )
}


def fetch_static(url: str) -> BeautifulSoup | None:
    """Fetch a page with requests and return a BeautifulSoup DOM, or None on error."""
    try:
        response = requests.get(url, headers=_REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(_decode_body(response), "html.parser")
    except requests.RequestException as exc:
        logger.error("Fetch error [%s]: %s", url, exc)
        return None


#: Explicit charset parameter in a Content-Type header, e.g. "text/html; charset=utf-8".
_CONTENT_CHARSET_RE = re.compile(r"charset=([\w.\-]+)", re.IGNORECASE)


def _declared_charset(response: requests.Response) -> str | None:
    """
    Return the charset explicitly written in the Content-Type header, or None.

    We do NOT trust requests' get_encoding_from_headers() for this: it falls
    back to 'ISO-8859-1' for any text/* without a charset, which is exactly
    the state we must distinguish from an explicit declaration.
    """
    content_type = response.headers.get("Content-Type", "")
    match = _CONTENT_CHARSET_RE.search(content_type)
    return match.group(1) if match else None


def _decode_body(response: requests.Response) -> str:
    """
    Decode response bytes with a sane charset strategy.

    requests falls back to ISO-8859-1 when the Content-Type carries no
    charset, which mangles UTF-8 docs ('' → 'â\x80\x99', 'ø' → 'Ã¸').
    Strategy: honor a charset explicitly declared in the response headers;
    otherwise decode UTF-8 strictly and fall back to the apparent encoding
    only if that fails (i.e. the page really is Latin-1).
    """
    if _declared_charset(response):
        return response.text

    content = response.content
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        if response.apparent_encoding:
            try:
                return content.decode(response.apparent_encoding)
            except (UnicodeDecodeError, LookupError):
                pass
    return content.decode("iso-8859-1", errors="replace")


def fetch_js(url: str) -> BeautifulSoup | None:
    """
    Fetch a JS-rendered page using headless Chromium via Playwright.

    Strategy (in order):
      1. Click the "Copy as Markdown" button if present — cleanest output.
      2. Fall back to reading .markdown-body inner text from the DOM.

    Returns a minimal BeautifulSoup wrapping the content in a <pre> tag so
    the downstream extract_content() can recover it via markdown_passthrough.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("playwright not installed — run: uv sync && uv run playwright install chromium")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            page    = context.new_page()

            logger.info("playwright: navigating …")
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
                logger.info("playwright: networkidle reached")
            except PWTimeout:
                logger.warning("playwright: networkidle timed out — continuing with current DOM")

            # ---- Strategy 1: Copy-as-Markdown button ----
            try:
                page.wait_for_selector("button:has-text('Markdown')", timeout=12_000)
                logger.info("playwright: clicking 'Copy as Markdown' button …")
                page.click("button:has-text('Markdown')")
                page.wait_for_timeout(800)
                content = page.evaluate("navigator.clipboard.readText()")
                logger.info("playwright: clipboard yielded %d chars", len(content))
                context.close()
                browser.close()
                return BeautifulSoup(f"<div><pre>{content}</pre></div>", "html.parser")
            except PWTimeout:
                logger.warning("playwright: no 'Copy as Markdown' button found — falling back to DOM")

            # ---- Strategy 2: .markdown-body innerText ----
            content = page.evaluate("document.querySelector('.markdown-body')?.innerText ?? ''")
            logger.info("playwright: DOM fallback yielded %d chars", len(content))
            context.close()
            browser.close()
            return BeautifulSoup(f"<div><pre>{content}</pre></div>", "html.parser")

    except Exception as exc:  # noqa: BLE001
        logger.error("playwright error: %s", exc)
        return None


def fetch(url: str, js_render: bool = False) -> BeautifulSoup | None:
    """Dispatch to the correct fetcher based on the js_render flag."""
    if js_render:
        logger.info("js-render  → %s", url)
        return fetch_js(url)
    logger.info("fetching   → %s", url)
    return fetch_static(url)


__all__ = ["fetch", "fetch_static", "fetch_js", "_decode_body", "_declared_charset", "_REQUEST_HEADERS"]
