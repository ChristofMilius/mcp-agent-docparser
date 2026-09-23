"""
crawl.py — Site crawl layer
============================
Discover the pages of a documentation site and fetch them concurrently
through the existing fetch → extract → emit pipeline.

Discovery sources, in order:
  1. robots.txt `Sitemap:` directives → sitemap index → leaf sitemaps.
  2. /sitemap.xml (or /sitemap_index.xml) when robots lists none.
  3. Same-host link walk from the seed URL when no sitemap exists.

Politeness (robots-strict): every candidate URL passes through the site's
robots.txt (urllib.robotparser) before any fetch is made, and a declared
`Crawl-delay` throttles the concurrent workers. An unreachable per-site
robots.txt is treated as allow-all (Scrapy convention); the decision is
logged.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from mcp_agent_docparser.emit import render_markdown, write_markdown
from mcp_agent_docparser.extract import extract_content
from mcp_agent_docparser.fetch import _REQUEST_HEADERS, fetch, fetch_static
from mcp_agent_docparser.receipts import _normalise_receipt

logger = logging.getLogger(__name__)

_SITEMAPS_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_DEFAULT_WORKERS = 8


# ----------------------------------------------------------------------
# URL helpers
# ----------------------------------------------------------------------


def _origin(url: str) -> str:
    """Scheme + netloc, e.g. 'https://docs.example.com'."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _norm_key(url: str) -> str:
    """Dedup key: scheme://netloc/path — no fragment, no trailing slash."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


def _dedup(urls: list[str], origin: str | None = None) -> list[str]:
    """Deduplicate URLs; optionally restrict to a single origin. Order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if origin is not None and _origin(url) != origin:
            continue
        key = _norm_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


# ----------------------------------------------------------------------
# robots.txt
# ----------------------------------------------------------------------


def _fetch_robots(seed_url: str) -> tuple[str | None, str]:
    """
    Fetch robots.txt for the seed's origin. Returns (body, robots_url);
    body is None when the fetch failed or the status is an error.
    """
    robots_url = f"{_origin(seed_url)}/robots.txt"
    try:
        response = requests.get(robots_url, headers=_REQUEST_HEADERS, timeout=15)
    except requests.RequestException:
        logger.warning("crawl: could not fetch %s — assuming allow-all", robots_url)
        return None, robots_url
    if response.status_code >= 400:
        logger.warning(
            "crawl: robots.txt returned HTTP %d for %s — assuming allow-all",
            response.status_code, robots_url,
        )
        return None, robots_url
    return response.text, robots_url


def _sitemap_lines(seed_url: str) -> list[str]:
    """URLs named by `Sitemap:` directives in the seed's robots.txt."""
    body, _ = _fetch_robots(seed_url)
    if not body:
        return []
    out: list[str] = []
    for line in body.splitlines():
        strip = line.strip()
        if strip.lower().startswith("sitemap:"):
            out.append(strip.split(":", 1)[1].strip())
    return out


def _robot_rules(seed_url: str, user_agent: str) -> tuple[robotparser.RobotFileParser, float]:
    """
    Parse the seed site's robots.txt. Returns (parser, crawl_delay).
    An empty parser (unreachable/absent robots.txt) allows everything.
    """
    parser = robotparser.RobotFileParser()
    body, _ = _fetch_robots(seed_url)
    lines = (body or "").splitlines()
    parser.parse(lines)
    delay = 0.0
    for line in lines:
        if line.strip().lower().startswith("crawl-delay:"):
            try:
                delay = max(0.0, float(line.split(":", 1)[1].strip()))
            except ValueError:
                delay = 0.0
    logger.info("crawl: robots rules for %s — crawl_delay=%s", user_agent[:20], delay)
    return parser, delay


# ----------------------------------------------------------------------
# Sitemaps
# ----------------------------------------------------------------------


def _parse_sitemap(url: str) -> tuple[list[str], list[str]]:
    """Fetch a sitemap; return (leaf page urls, nested sitemap urls)."""
    try:
        response = requests.get(url, headers=_REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("crawl: could not fetch sitemap %s", url)
        return [], []
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        logger.warning("crawl: sitemap %s is not well-formed XML", url)
        return [], []

    pages: list[str] = []
    nested: list[str] = []
    for el in root:
        tag = el.tag.rsplit("}", 1)[-1]  # "url" or "sitemap", namespaced or not
        loc = el.findtext(f"{{{_SITEMAPS_NS}}}loc") or el.findtext("loc")
        if not loc or not loc.strip():
            continue
        loc = loc.strip()
        if tag == "url":
            pages.append(loc)
        elif tag == "sitemap":
            nested.append(loc)
    return pages, nested


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def discover_urls(
    seed_url: str,
    *,
    max_pages: int = 200,
    path_prefix: str | None = None,
    user_agent: str = _REQUEST_HEADERS["User-Agent"],
) -> dict:
    """
    Discover candidate page URLs for a seed documentation URL.

    Returns:
      urls:          allowed, deduped, sorted page URLs (same origin as seed)
      source:        "sitemap" | "link_walk" | "seed"
      crawl_delay:   seconds honored between page fetches (robots Crawl-delay)
      robots_denied: how many candidates robots.txt refused
    """
    robots, crawl_delay = _robot_rules(seed_url, user_agent)
    origin = _origin(seed_url)

    candidates: list[str] = []
    source = "link_walk"

    if urlsplit(seed_url).path.lower().endswith(".xml"):
        # Seed is itself a sitemap — parse it directly.
        candidates = _parse_sitemap(seed_url)[0]
        source = "seed"
    else:
        queue: deque[str] = deque(_sitemap_lines(seed_url))
        if not queue:
            queue.append(f"{origin}/sitemap.xml")
        seen_sitemaps: set[str] = set()
        while queue and len(candidates) < max_pages:
            sitemap_url = queue.popleft()
            key = _norm_key(sitemap_url)
            if key in seen_sitemaps:
                continue
            seen_sitemaps.add(key)
            pages, nested = _parse_sitemap(sitemap_url)
            candidates.extend(pages)
            queue.extend(nested)
        if candidates:
            source = "sitemap"

    allowed: list[str] = []
    denied = 0
    for url in _dedup(candidates, origin):
        if not robots.can_fetch(user_agent, url):
            denied += 1
            continue
        if path_prefix and not urlsplit(url).path.startswith(path_prefix):
            continue
        allowed.append(url)
    allowed.sort()

    if not allowed:
        allowed = _link_walk(
            seed_url,
            robots=robots,
            user_agent=user_agent,
            max_pages=max_pages,
            path_prefix=path_prefix,
        )
        source = "link_walk"
    else:
        allowed = allowed[:max_pages]

    logger.info("crawl: discovered %d URL(s) for %s via %s", len(allowed), seed_url, source)
    return {
        "urls": allowed,
        "source": source,
        "crawl_delay": crawl_delay,
        "robots_denied": denied,
    }


def _link_walk(
    seed_url: str,
    *,
    robots: robotparser.RobotFileParser,
    user_agent: str,
    max_pages: int,
    path_prefix: str | None,
) -> list[str]:
    """
    Same-origin BFS from the seed, collecting pages that pass robots.txt.
    Only the seed itself is known to be fetchable; all further hops check
    robots before fetching.
    """
    origin = _origin(seed_url)
    visited: set[str] = set()
    queue: deque[str] = deque([seed_url])
    found: list[str] = []
    hard_ceiling = max_pages * 10

    while queue and len(found) < max_pages:
        if len(visited) >= hard_ceiling:
            logger.warning("crawl: link-walk hit hard ceiling at %d visited", hard_ceiling)
            break
        url = queue.popleft()
        key = _norm_key(url)
        if key in visited:
            continue
        visited.add(key)
        if path_prefix and not urlsplit(url).path.startswith(path_prefix):
            continue
        if not robots.can_fetch(user_agent, url):
            continue
        soup = fetch_static(url)
        if soup is None:
            continue
        found.append(url)
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            absolute = urljoin(url, href)
            if _origin(absolute) != origin or _norm_key(absolute) in visited:
                continue
            queue.append(absolute)
    return found


# ----------------------------------------------------------------------
# Crawl execution
# ----------------------------------------------------------------------


class _Throttle:
    """Inter-worker request throttle honoring robots Crawl-delay."""

    def __init__(self, delay: float) -> None:
        self._delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self._delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
            self._next_at = max(now, self._next_at) + self._delay


def _extract_page(url: str, template: dict, throttle: _Throttle) -> tuple[str, str | None]:
    throttle.wait()
    soup = fetch(url, js_render=template.get("js_render", False))
    if soup is None:
        return url, None
    return url, extract_content(soup, template)


def crawl_site(
    template: dict,
    seed_url: str,
    *,
    output_dir: Path,
    key: str | None = None,
    max_pages: int = 200,
    path_prefix: str | None = None,
    workers: int = _DEFAULT_WORKERS,
    dry_run: bool = False,
) -> dict:
    """
    Discover a site's pages via `discover_urls`, fetch them concurrently,
    extract each through the template receipt, and emit one combined .md.

    dry_run=True performs discovery only — no page is fetched.
    """
    template = _normalise_receipt(template)
    discovery = discover_urls(seed_url, max_pages=max_pages, path_prefix=path_prefix)
    urls = discovery["urls"]

    result: dict = {
        "status": "dry_run",
        "key": key,
        "name": template["name"],
        "mode": "crawl",
        "seed": seed_url,
        "max_pages": max_pages,
        "path_prefix": path_prefix,
        "source": discovery["source"],
        "crawl_delay": discovery["crawl_delay"],
        "robots_denied": discovery["robots_denied"],
        "urls_discovered": len(urls),
    }
    if dry_run:
        result["urls"] = urls
        return result

    throttle = _Throttle(discovery["crawl_delay"])
    sections: list[tuple[str, str]] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_page, url, template, throttle): url for url in urls}
        for future in as_completed(futures):
            url, content = future.result()
            if content is None:
                failed += 1
                logger.warning("crawl: no content extracted from %s", url)
                continue
            sections.append((url, content))

    if not sections:
        return {**result, "status": "error", "error": "No content extracted during crawl."}

    sections.sort(key=lambda item: item[0])
    filepath = write_markdown(template, sections, output_dir)
    total_chars = sum(len(content) for _, content in sections)

    return {
        **result,
        "status": "ok",
        "pages_fetched": len(sections),
        "pages_failed": failed,
        "output_dir": str(output_dir),
        "output_filename": filepath.name,
        "sections": [{"url": url, "chars": len(content)} for url, content in sections],
        "total_chars": total_chars,
        "markdown": render_markdown(template, sections),
    }


__all__ = [
    "crawl_site",
    "discover_urls",
    "_dedup",
    "_norm_key",
    "_origin",
    "_parse_sitemap",
    "_robot_rules",
    "_sitemap_lines",
    "_link_walk",
]
