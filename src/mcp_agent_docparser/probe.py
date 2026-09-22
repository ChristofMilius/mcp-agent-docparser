"""
probe.py — Probe layer (selector discovery for an unknown page)
================================================================
Ported from the terminal-menu docparser. The original printed a coloured
report; server mode returns a structured dict that tools can hand back to
the model as JSON.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

from mcp_agent_docparser.fetch import fetch_static

logger = logging.getLogger(__name__)

_PROBE_SELECTORS = [
    "#content", ".prose", "article", "main", "[role='main']",
    ".content", ".docs-content", ".markdown-body",
    ".md-content", ".page-content", "[class*='mdx']",
    "[class*='article']", "[class*='doc-content']",
]


def _analyse_probe_soup(soup: BeautifulSoup) -> dict:
    """
    Walk _PROBE_SELECTORS against a parsed DOM and report hits, H2 structure,
    and sample links. Used by probe_url and probe_url_js.
    """
    hits: list[str]   = []
    misses: list[str] = []
    hit_details: list[dict] = []
    first_match: Tag | None = None

    for sel in _PROBE_SELECTORS:
        el = soup.select_one(sel)
        if el:
            classes = " ".join(el.get("class", []))[:60]
            hit_details.append({"selector": sel, "tag": el.name, "class": classes})
            hits.append(sel)
            if first_match is None:
                first_match = el
        else:
            misses.append(sel)

    h2s: list[str] = []
    links: list[str] = []
    if first_match is not None:
        h2s = [h.get_text().strip()[:70] for h in first_match.find_all("h2")][:15]
        links = [a["href"] for a in first_match.find_all("a", href=True)
                 if a["href"].startswith("http")][:10]
    else:
        logger.warning("No selector matched for probe — page may be JS-rendered.")

    return {
        "hits":          hits,
        "misses":        misses,
        "hit_details":   hit_details,
        "h2s":           h2s,
        "links":         links,
        "best_selector": hits[0] if hits else None,
    }


def probe_url(url: str) -> dict | None:
    """
    Fetch a page statically and report which CSS selectors match and what
    H2 structure exists. Returns a dict of probe findings, or None if the
    page could not be fetched.
    """
    logger.info("Probing (static): %s", url)
    soup = fetch_static(url)
    if soup is None:
        return None

    findings = _analyse_probe_soup(soup)
    findings["url"]         = url
    findings["js"]          = False
    findings["copy_button"] = None
    return findings


def probe_url_js(url: str) -> dict | None:
    """
    Probe a JS-rendered page with headless Chromium.

    Loads the URL in Playwright, waits for the network to settle, then runs
    the same selector report over the *rendered* DOM. Also detects a
    'Copy as Markdown' button so a saved receipt can pre-fill
    markdown_passthrough automatically.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("playwright not installed — run: uv sync && uv run playwright install chromium")
        return None

    logger.info("Probing (JS): %s", url)

    html = ""
    copy_button = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page    = context.new_page()

            logger.info("playwright: navigating …")
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
                logger.info("playwright: networkidle reached")
            except PWTimeout:
                logger.warning("playwright: networkidle timed out — continuing with current DOM")

            page.wait_for_timeout(1_000)   # let late hydration settle

            copy_button = page.locator("button:has-text('Markdown')").count() > 0
            if copy_button:
                logger.info("'Copy as Markdown' button detected — saved receipt will use markdown_passthrough.")

            html = page.content()
            logger.info("playwright: captured %d chars of rendered HTML", len(html))

            context.close()
            browser.close()

    except Exception as exc:  # noqa: BLE001
        logger.error("playwright error: %s", exc)
        return None

    soup = BeautifulSoup(html, "html.parser")
    findings = _analyse_probe_soup(soup)
    findings["url"]         = url
    findings["js"]          = True
    findings["copy_button"] = copy_button
    return findings


__all__ = ["probe_url", "probe_url_js", "_PROBE_SELECTORS"]
