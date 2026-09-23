"""
parse.py — Core parse action
=============================
Ported from the terminal-menu docparser's parse_receipt. The original printed
progress and returned None; server mode returns a structured dict so tools
can hand results back to the model as JSON.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mcp_agent_docparser.emit import render_markdown, write_markdown
from mcp_agent_docparser.extract import extract_content
from mcp_agent_docparser.fetch import close_js_session, fetch
from mcp_agent_docparser.receipts import ReceiptRegistry

logger = logging.getLogger(__name__)


def parse_receipt(
    key: str,
    registry: ReceiptRegistry,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Fetch all URLs in a receipt, extract content, emit a .md file, and
    update the registry with last_fetched / last_output.

    Returns a structured dict:
      status: "ok" | "dry_run" | "not_found" | "error"
      ...status-specific fields...

    dry_run=True fetches nothing and reports what would be done.
    """
    receipt = registry.get(key)
    if receipt is None:
        return {"status": "not_found", "key": key}

    urls         = receipt.get("urls", [])
    js_render    = receipt.get("js_render", False)
    js_settle_ms = receipt.get("js_settle_ms")

    if not urls:
        return {"status": "error", "key": key, "error": "receipt has no URLs defined."}

    logger.info(
        "Parsing %s — %d URL(s), js_render=%s, passthrough=%s",
        receipt["name"], len(urls), js_render, receipt.get("markdown_passthrough", False),
    )

    if dry_run:
        return {
            "status": "dry_run",
            "key": key,
            "name": receipt["name"],
            "urls": urls,
            "js_render": js_render,
            "markdown_passthrough": receipt.get("markdown_passthrough", False),
        }

    sections: list[tuple[str, str]] = []
    for url in urls:
        soup = fetch(url, js_render=js_render, js_settle_ms=js_settle_ms)
        if soup is None:
            logger.warning("Skipping %s — fetch failed", url)
            continue
        content = extract_content(soup, receipt)
        sections.append((url, content))
        logger.info("extracted %d chars from %s", len(content), url)

    if js_render:
        close_js_session()

    if not sections:
        return {
            "status": "error",
            "key": key,
            "name": receipt["name"],
            "error": "No content extracted — check receipt URLs and selectors.",
        }

    filepath = write_markdown(receipt, sections, output_dir)
    registry.mark_fetched(key, filepath.name)

    return {
        "status": "ok",
        "key": key,
        "name": receipt["name"],
        "output_dir": str(output_dir),
        "output_filename": filepath.name,
        "sections": [
            {"url": url, "chars": len(content)} for url, content in sections
        ],
        "total_chars": sum(len(content) for _, content in sections),
        "markdown": render_markdown(receipt, sections),
    }


__all__ = ["parse_receipt"]
