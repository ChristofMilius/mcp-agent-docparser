"""
fetch.py — Fetch layer (static + JS-rendered)
=============================================
Ported from the terminal-menu docparser. server mode routes messages through
the logging module instead of printing (stdio must stay clean).
"""

from __future__ import annotations

import atexit
import logging
import re
import threading

import requests
from bs4 import BeautifulSoup

from mcp_agent_docparser.cache import cache_get, cache_put

logger = logging.getLogger(__name__)

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0 Safari/537.36"
    )
}

#: Regexes that flag clipboard content as raw page *source* rather than
#: rendered/copyable markdown. Sites sometimes wire "Copy page" to write the
#: original MDX/MD file — YAML frontmatter and import/JSX blocks give it away.
#: An empty string never flags.
_SOURCE_SNIFFERS = [
    re.compile(r"^\s*---\s*\n", re.MULTILINE),  # YAML frontmatter opener
    re.compile(r"^\s*import\s+[{\w\"'@\[]", re.MULTILINE),  # ESM/TS imports
]


def _reject_source_clipboard(content: str) -> bool:
    """True when clipboard text looks like raw source rather than markdown."""
    if not content or not content.strip():
        return True  # empty payload is always unusable
    return any(sniff.search(content) for sniff in _SOURCE_SNIFFERS)


#: Button selectors for the "Copy as Markdown" strategy, tried in order.
#: Sites label the button differently ("Copy as Markdown", "Copy markdown",
#: a bare "Markdown", or a data-driven widget). "Copy page" is the common
#: phrase on Mintlify/Nextra themes (they copy the page as markdown).
_COPY_MD_SELECTORS = [
    "button:has-text('Copy as Markdown')",
    "button:has-text('Copy markdown')",
    "button:has-text('Copy page')",
    "button:has-text('Markdown')",
    "[data-copy-markdown]",
    ".copy-markdown",
]

#: Content containers tried when there is no copy button. The first one that
#: actually holds text is serialized as structured HTML so receipt selectors
#: still apply downstream.
_DOM_FALLBACK_SELECTORS = [
    ".markdown-body",
    "article",
    "main",
    "[role='main']",
    ".content",
    "#content",
]

#: Default hydration/settle delay before probing for the copy button.
_DEFAULT_JS_SETTLE_MS = 800

#: Live Playwright sessions across threads, for at-exit cleanup.
_JS_SESSIONS: set[object] = set()
_JS_SESSIONS_LOCK = threading.Lock()
_js_local = threading.local()


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


class _JsPlaywright:
    """
    Lazy single-browser Playwright session bound to its creating thread.

    Playwright's sync API is thread-bound, so a process keeps one session per
    thread that renders JS (parse_receipt runs one; each crawl worker gets its
    own). The browser stays alive across URLs — the expensive launch happens
    once per thread instead of once per page — and is stopped by
    `close_js_session()` or at process exit.
    """

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright

        self.owner = threading.current_thread()
        self._pw = None
        self._browser = None
        self._context = None
        self._closed = False
        self._pw = sync_playwright().start()
        with _JS_SESSIONS_LOCK:
            _JS_SESSIONS.add(self)

    def _context_for(self) -> object:
        if self._context is None or self._context.is_closed():
            if self._browser is None or not self._browser.is_connected():
                self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                permissions=["clipboard-read", "clipboard-write"]
            )
        return self._context

    def new_page(self) -> object:
        return self._context_for().new_page()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._context is not None:
                self._context.close()
        finally:
            try:
                if self._browser is not None:
                    self._browser.close()
            finally:
                if self._pw is not None:
                    self._pw.stop()
        with _JS_SESSIONS_LOCK:
            _JS_SESSIONS.discard(self)


def _get_session() -> _JsPlaywright:
    """Return this thread's Playwright session, launching one on first use."""
    session = getattr(_js_local, "session", None)
    if session is None:
        session = _JsPlaywright()
        _js_local.session = session
    return session


def close_js_session() -> None:
    """Stop this thread's Playwright browser (see _JsPlaywright)."""
    session = getattr(_js_local, "session", None)
    if session is not None:
        logger.info("playwright: closing thread-private session")
        session.close()
        _js_local.session = None


def _shutdown_js_sessions() -> None:
    """Best-effort stop of every live session at interpreter exit."""
    with _JS_SESSIONS_LOCK:
        sessions = list(_JS_SESSIONS)
    for session in sessions:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


atexit.register(_shutdown_js_sessions)


def fetch_js(url: str, *, js_settle_ms: int | None = None) -> BeautifulSoup | None:
    """
    Fetch a JS-rendered page using headless Chromium via Playwright.

    Strategy (in order):
      1. Click the first button matching `_COPY_MD_SELECTORS` — cleanest
         output, recovered via clipboard markdown into a <pre>.
      2. Serialize the first text-bearing content container from
         `_DOM_FALLBACK_SELECTORS` as structured HTML, so receipt selectors
         still apply downstream.
      3. Last resort: body innerText wrapped in a <pre> for passthrough.

    A Playwright session is reused across calls on the same thread. Navigation
    that times out on networkidle is retried once with domcontentloaded.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
    except ImportError:
        logger.error(
            "playwright not installed — run: uv sync && uv run playwright install chromium"
        )
        return None

    settle = _DEFAULT_JS_SETTLE_MS if js_settle_ms is None else max(0, js_settle_ms)

    page = None
    try:
        session = _get_session()
        page = session.new_page()

        logger.info("playwright: navigating %s …", url)
        try:
            page.goto(url, wait_until="networkidle", timeout=45_000)
            logger.info("playwright: networkidle reached")
        except PWTimeout:
            logger.warning("playwright: networkidle timed out for %s — retrying once", url)
            page.wait_for_timeout(500)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                logger.info("playwright: domcontentloaded retry reached")
            except PWTimeout:
                logger.warning(
                    "playwright: domcontentloaded retry timed out — continuing with current DOM"
                )

        page.wait_for_timeout(settle)  # let late hydration populate the button

        # ---- Strategy 1: Copy-as-Markdown button ----
        button_sel = None
        button_loc = None
        for sel in _COPY_MD_SELECTORS:
            locator = page.locator(sel).first
            if locator.count() > 0:
                button_sel, button_loc = sel, locator
                break
        if button_loc is not None:
            try:
                logger.info("playwright: clicking %s …", button_sel)
                button_loc.click()
                page.wait_for_timeout(800)
                content = page.evaluate("navigator.clipboard.readText()")
                if content.strip() and not _reject_source_clipboard(content):
                    logger.info("playwright: clipboard yielded %d chars", len(content))
                    return BeautifulSoup(f"<div><pre>{content}</pre></div>", "html.parser")
                logger.warning(
                    "playwright: clipboard unusable (%d chars) — falling back to DOM",
                    len(content),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("playwright: copy-markdown failed (%s) — falling back to DOM", exc)

        # ---- Strategy 2: structured content container ----
        html = page.evaluate(
            """
            (() => {
              const selectors = [".markdown-body", "article", "main", "[role='main']",
                                 ".content", "#content"];
              for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && (el.textContent || "").trim().length > 200) return el.outerHTML;
              }
              return "";
            })()
            """
        )
        if html.strip():
            logger.info("playwright: structured DOM fallback yielded %d chars", len(html))
            return BeautifulSoup(f"<div>{html}</div>", "html.parser")

        # ---- Strategy 3: loose text blob ----
        blob = page.evaluate("document.body?.innerText ?? ''")
        logger.info("playwright: innerText fallback yielded %d chars", len(blob))
        return BeautifulSoup(f"<div><pre>{blob}</pre></div>", "html.parser")

    except Exception as exc:  # noqa: BLE001
        logger.error("playwright error: %s", exc)
        return None
    finally:
        if page is not None:
            page.close()


def fetch(
    url: str, js_render: bool = False, js_settle_ms: int | None = None
) -> BeautifulSoup | None:
    """Dispatch to the correct fetcher based on the js_render flag."""
    cached = cache_get(url, js_render)
    if cached is not None:
        logger.info("cache-hit  → %s", url)
        return BeautifulSoup(cached, "html.parser")
    if js_render:
        logger.info("js-render  → %s", url)
        soup = fetch_js(url, js_settle_ms=js_settle_ms)
    else:
        logger.info("fetching   → %s", url)
        soup = fetch_static(url)
    if soup is not None:
        cache_put(url, js_render, str(soup))
    return soup


__all__ = [
    "fetch",
    "fetch_static",
    "fetch_js",
    "close_js_session",
    "_decode_body",
    "_declared_charset",
    "_REQUEST_HEADERS",
    "_COPY_MD_SELECTORS",
    "_DOM_FALLBACK_SELECTORS",
]
