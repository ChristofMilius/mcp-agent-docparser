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

#: Class markers like language-python / language-json on <code> elements.
_CODE_LANG_CLASS_RE = re.compile(r"language-([a-zA-Z0-9#+_-]+)")

#: Tokens that unambiguously name a *code* language (not a human language
#: like "english"). Used as a fallback when a receipt carries no explicit
#: code_language and the page offers no data-language / language-* hint.
_TRAILING_CODE_LANGS = {
    "python", "py", "python3", "js", "javascript", "node", "typescript", "ts",
    "json", "jsonc", "bash", "sh", "shell", "zsh", "powershell", "ps1",
    "go", "golang", "rust", "c", "cpp", "c++", "csharp", "java", "kotlin",
    "ruby", "php", "swift", "sql", "html", "css", "scss", "yaml", "yml",
    "toml", "makefile", "dockerfile", "markdown", "md", "text", "plaintext",
    "none",
}

#: Self-referenced heading anchors — Sphinx/MkDocs "[¶](#quickstart ...)" and
#: Docusaurus "[​](#quickstart ... "Direct link to ...")" (a zero-width space
#: U+200B as the link text). Matches the inline link only — the newline(s)
#: after it stay so the heading keeps its own line instead of gluing to the
#: following paragraph.
_HEADING_ANCHOR_RE = re.compile(r"\[[¶^\u200b]\]\(#[^)]*\)")

#: Markdown heading line → unwrap self-referencing links: "[Use a plugin](#use-a-plugin)"
#: becomes plain "Use a plugin" (Astro/mdx docs wrap heading text in the anchor link).
_HEADING_SELF_LINK_RE = re.compile(
    r"^(\s*#+\s*)\[([^\]]+)\]\(#[^\s)]*(?:\s+\"[^\"]*\")?\)\s*$",
    re.MULTILINE,
)

#: Trailing heading-anchor token in raw copy-markdown, e.g. "Use a skill [#use-a-skill]".
_HEADING_HASH_TOKEN_RE = re.compile(r"^(.*?)\s+\[#([\w-]+)\]\s*$", re.MULTILINE)

#: Minimum direct text for a div/section to qualify as a fallback candidate.
_MIN_CONTENT_CHARS = 200


def _to_kebab(text: str) -> str:
    """'Use a skill' → 'use-a-skill' (matches anchor slugs)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _content_score(el: Tag) -> int:
    """
    Heuristic content score for the fallback: text length minus link text,
    plus code-block richness.

    Link text is already counted inside the raw text, so subtracting it twice
    discounts nav/menu/list boxes. Code blocks are dense signal (docs pages
    are full of them) and push a block up.
    """
    text_chars = len(el.get_text(" ", strip=True))
    link_chars = sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a"))
    code_blocks = len(el.find_all("pre"))
    return text_chars - 2 * link_chars + 150 * code_blocks


def select_best_content(soup: BeautifulSoup) -> Tag | None:
    """
    Score-based fallback for the selectors walk.

    When no plain CSS selector matches, candidate the page structure itself:
    semantic content tags (article/main) plus any section/div holding at least
    `_MIN_CONTENT_CHARS` of text. Rank by `_content_score`; return the winner,
    or None when nothing convincingly content-like exists.
    """
    candidates: list[Tag] = []
    seen: set[int] = set()

    for selector in ("article", "main", "[role='main']"):
        el = soup.select_one(selector)
        if el is not None and id(el) not in seen:
            seen.add(id(el))
            candidates.append(el)

    for el in soup.find_all(["section", "div"]):
        if id(el) in seen:
            continue
        if len(el.get_text(" ", strip=True)) < _MIN_CONTENT_CHARS:
            continue
        candidates.append(el)

    if not candidates:
        return None

    best = max(candidates, key=_content_score)
    if _content_score(best) <= 0:
        return None
    return best


def css_hint(tag: Tag) -> str:
    """Best-effort CSS selector hint for a tag: id > first class > tag name."""
    if tag.get("id"):
        return f"#{tag['id']}"
    classes = tag.get("class") or []
    if classes:
        return f"{tag.name}.{classes[0]}"
    return tag.name


def _strip_heading_hash_tokens(text: str) -> str:
    """Drop trailing '[#anchor-slug]' tokens only when the slug matches the line text."""
    def _repl(match: re.Match) -> str:
        body, slug = match.group(1), match.group(2)
        if _to_kebab(body) == slug:
            return body
        return match.group(0)

    return _HEADING_HASH_TOKEN_RE.sub(_repl, text)


def extract_content(soup: BeautifulSoup, receipt: dict) -> str:
    """
    Locate the best content block, strip noise, and return clean markdown.

    Steps:
      1. If markdown_passthrough is set, treat the first <pre> as raw markdown.
      2. Walk the selector list — first CSS selector that matches wins.
      3. Remove strip_tags elements in place.
      4. Collapse expressive-code <pre> blocks into plain line text.
      5. Resolve the code-fence language (explicit, detected, or fallback).
      6. Optionally restrict to a named H2 section.
      7. Convert HTML → markdown via markdownify.
      8. Strip heading-anchor noise and collapse excessive blank lines.
    """
    # ---- Passthrough: content is already markdown (e.g. from Playwright clipboard) ----
    if receipt.get("markdown_passthrough"):
        pre = soup.find("pre")
        text = pre.get_text() if pre else soup.get_text()
        return _clean_passthrough(text)

    # ---- Selector walk ----
    content_block: Tag | None = None
    for selector in receipt["selectors"]:
        found = soup.select_one(selector)
        if found:
            content_block = found
            break

    if content_block is None:
        content_block = select_best_content(soup)

    if content_block is None:
        return "_No content block matched any selector for this page._\n"

    # ---- Strip noise ----
    for selector in receipt.get("strip_tags") or []:
        for element in content_block.select(selector):
            element.decompose()

    # ---- Collapse expressive-code <pre> blocks (ec-line divs → plain lines) ----
    _collapse_pre_blocks(content_block, soup)

    # ---- Code-fence language: explicit > detected > plausible fallback > bare ----
    fence_language = _resolve_code_language(content_block, receipt)

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
        code_language=fence_language,
    )
    raw_md = _HEADING_ANCHOR_RE.sub("", raw_md)
    raw_md = _HEADING_SELF_LINK_RE.sub(r"\1\2", raw_md)
    return re.sub(r"\n{3,}", "\n\n", raw_md).strip()


def _clean_passthrough(text: str) -> str:
    """
    Normalize raw copy-markdown (Playwright clipboard): CRLF → LF, trailing
    [#anchor-slug] tokens off headings, whitespace-only line collapse.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_heading_hash_tokens(text)
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _collapse_pre_blocks(content_block: Tag, soup: BeautifulSoup) -> None:
    """
    Rebuild <pre> blocks whose lines are wrapped in individual divs
    (expressive-code ".ec-line", Docusaurus Prism ".token-line") as one
    <pre><code> block of plain lines.

    Without this, markdownify emits a blank line between every code line
    (each wrapper div becomes its own paragraph).
    """
    for pre in content_block.find_all("pre"):
        code = pre.find("code") or pre
        line_els = (
            code.select(".ec-line")
            or code.select(".line")
            or code.select(".token-line")
        )
        if not line_els:
            continue
        text = "\n".join(el.get_text() for el in line_els) + "\n"

        new_pre = soup.new_tag("pre")
        for attr, value in pre.attrs.items():
            new_pre[attr] = value
        new_code = soup.new_tag("code")
        new_code.string = text
        new_pre.append(new_code)
        pre.replace_with(new_pre)


def _detect_code_language(content_block: Tag) -> str | None:
    """Collect data-language / language-* hints from <pre>/<code>; most common wins."""
    mentions: dict[str, int] = {}
    for pre in content_block.find_all("pre"):
        hint = pre.get("data-language")
        if hint:
            mentions[str(hint)] = mentions.get(str(hint), 0) + 1
        # Docusaurus Prism puts "language-mojo" on the <pre>, not the <code>
        for node in (pre, *pre.find_all("code")):
            for cls in node.get("class") or []:
                match = _CODE_LANG_CLASS_RE.match(cls)
                if match:
                    lang = match.group(1)
                    mentions[lang] = mentions.get(lang, 0) + 1
    if not mentions:
        return None
    return max(mentions, key=mentions.get)


def _resolve_code_language(content_block: Tag, receipt: dict) -> str:
    """
    Pick the language used for ``` fences.

    Priority: explicit receipt `code_language` field, then page-detected
    data-language / language-* hints, then the receipt `language` *only when
    it names a code language* (not a human language like "english"). Empty
    string renders a bare ``` fence.
    """
    explicit = receipt.get("code_language")
    if explicit:
        return explicit
    detected = _detect_code_language(content_block)
    if detected:
        return detected
    lang = (receipt.get("language") or "").strip()
    if lang.lower() in _TRAILING_CODE_LANGS:
        return lang
    return ""


__all__ = [
    "extract_content",
    "_clean_passthrough",
    "_collapse_pre_blocks",
    "_detect_code_language",
    "_resolve_code_language",
    "_TRAILING_CODE_LANGS",
    "select_best_content",
    "css_hint",
]
