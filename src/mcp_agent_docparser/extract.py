"""
extract.py — Extract layer
==========================
Locate the best content block, strip noise, return clean markdown.
Ported from the terminal-menu docparser (logic unchanged).
"""

from __future__ import annotations

import re

import markdownify
from bs4 import BeautifulSoup, Tag


def extract_content(soup: BeautifulSoup, receipt: dict) -> str:
    """
    Locate the best content block, strip noise, and return clean markdown.

    Steps:
      1. If markdown_passthrough is set, treat the first <pre> as raw markdown.
      2. Walk the selector list — first CSS selector that matches wins.
      3. Remove strip_tags elements in place.
      4. Optionally restrict to a named H2 section.
      5. Convert HTML → markdown via markdownify.
      6. Collapse excessive blank lines.
    """
    # ---- Passthrough: content is already markdown (e.g. from Playwright clipboard) ----
    if receipt.get("markdown_passthrough"):
        pre = soup.find("pre")
        return pre.get_text() if pre else soup.get_text()

    # ---- Selector walk ----
    content_block: Tag | None = None
    for selector in receipt["selectors"]:
        found = soup.select_one(selector)
        if found:
            content_block = found
            break

    if content_block is None:
        return "_No content block matched any selector for this page._\n"

    # ---- Strip noise ----
    for selector in receipt.get("strip_tags") or []:
        for element in content_block.select(selector):
            element.decompose()

    # ---- Optional H2 section filter ----
    section_filter: str | None = receipt.get("section")
    if section_filter:
        capturing = False
        kept: list[str] = []
        for tag in content_block.find_all(True, recursive=False):
            if tag.name == "h2" and section_filter.lower() in tag.get_text().lower():
                capturing = True
                continue
            if tag.name == "h2" and capturing:
                break
            if capturing:
                kept.append(str(tag))
        html_fragment = "\n".join(kept) if kept else str(content_block)
    else:
        html_fragment = str(content_block)

    # ---- HTML → Markdown ----
    raw_md = markdownify.markdownify(
        html_fragment,
        heading_style="ATX",
        bullets="-",
        code_language=receipt["language"],
    )
    return re.sub(r"\n{3,}", "\n\n", raw_md).strip()


__all__ = ["extract_content"]
