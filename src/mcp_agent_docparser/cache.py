"""
cache.py — Fetch-level HTML cache
=================================
Caches each fetched page so repeated parses and crawls skip the network (and,
for JS-rendered pages, the headless-browser render).

The cache sits at the `fetch()` dispatcher — below the receipts, above the
requests/Playwright layer. Static and JS renders of the same URL can
legitimately produce different DOMs, so the storage key includes the variant:
a static entry never serves a JS parse, and vice versa.

Probe and crawl discovery deliberately bypass the cache (they call
`fetch_static` directly) because they must observe the live web.

Env:
  DOCPARSER_CACHE_DIR           cache root directory; relative values resolve
                                against the project root. Default "cache".
  DOCPARSER_CACHE_TTL_SECONDS   seconds an entry stays fresh; 0 (default)
                                means never expire.
  DOCPARSER_CACHE_DISABLED      set to any of 1/true/yes to disable.

Concurrency: crawl workers and parse threads write entries concurrently.
Writes go to a temp file, then `os.replace` — a reader always sees either the
old or the new complete entry, never a partial one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from mcp_agent_docparser.config import _resolve_path

logger = logging.getLogger(__name__)

_ENTRY_SUFFIX = ".json"
_TMP_SUFFIX = ".tmp"

_DISABLED_VALUES = {"1", "true", "yes"}


def cache_enabled() -> bool:
    """False when DOCPARSER_CACHE_DISABLED carries a truthy value."""
    return os.getenv("DOCPARSER_CACHE_DISABLED", "").strip().lower() not in _DISABLED_VALUES


def cache_dir() -> Path:
    """Resolve the cache root directory from the environment."""
    return _resolve_path(os.getenv("DOCPARSER_CACHE_DIR", "cache"))


def _ttl_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("DOCPARSER_CACHE_TTL_SECONDS", "0")))
    except ValueError:
        return 0.0


def _variant(js_render: bool) -> str:
    return "js" if js_render else "static"


def _key(url: str, js_render: bool) -> str:
    return hashlib.sha256(f"{_variant(js_render)}:{url}".encode()).hexdigest()


def _entry_path(url: str, js_render: bool) -> Path:
    return cache_dir() / f"{_key(url, js_render)}{_ENTRY_SUFFIX}"


def _load_entry(path: Path) -> dict | None:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        logger.warning("cache: unreadable entry %s — treating as miss", path)
        return None


def cache_get(url: str, js_render: bool) -> str | None:
    """Return the cached HTML for (url, variant), or None on miss/expiry."""
    if not cache_enabled():
        return None
    path = _entry_path(url, js_render)
    entry = _load_entry(path)
    if entry is None:
        return None
    ttl = _ttl_seconds()
    fetched = entry.get("fetched_at", 0.0)
    if ttl > 0 and (time.time() - fetched) > ttl:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        logger.info("cache: expired entry for %s (ttl %ss)", url, ttl)
        return None
    html = entry.get("html")
    if not isinstance(html, str) or not html:
        return None
    return html


def cache_put(url: str, js_render: bool, html: str) -> Path | None:
    """Atomically store HTML for (url, variant). No-op when disabled/empty."""
    if not cache_enabled() or not html:
        return None
    path = _entry_path(url, js_render)
    payload = {
        "url": url,
        "variant": _variant(js_render),
        "fetched_at": time.time(),
        "html": html,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + _TMP_SUFFIX)
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp_path, path)
        return path
    except OSError as exc:
        logger.warning("cache: write failed for %s (%s)", url, exc)
        return None


def cache_clear() -> int:
    """Delete every cached entry; returns the number removed."""
    removed = 0
    d = cache_dir()
    try:
        if not d.is_dir():
            return 0
        for child in list(d.iterdir()):
            if child.is_file() and child.name.endswith(_ENTRY_SUFFIX):
                try:
                    child.unlink()
                    removed += 1
                except OSError:
                    pass
    except OSError as exc:
        logger.warning("cache: clear failed (%s)", exc)
    return removed


__all__ = [
    "cache_clear",
    "cache_dir",
    "cache_enabled",
    "cache_get",
    "cache_put",
    "_key",
]
