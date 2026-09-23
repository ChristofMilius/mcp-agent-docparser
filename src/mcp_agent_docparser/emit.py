"""
emit.py — Emit layer
====================
Write the extracted content to timestamped .md files.
Ported from the terminal-menu docparser.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

MAX_FILENAME_LEN = 80


def _safe_name(name: str) -> str:
    """Derive a filesystem-safe slug from a receipt's display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug[:MAX_FILENAME_LEN].strip("_") or "doc"


def render_markdown(receipt: dict, sections: list[tuple[str, str]]) -> str:
    """
    Build the full .md body for a receipt.

    Each (url, content) pair in sections becomes a <!-- SOURCE: url --> block.
    Returns the rendered text (does not touch the filesystem).
    """
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        f"# {receipt['name']}",
        "",
        f"- **Language:** `{receipt['language']}`",
        f"- **Fetched:** {fetched_at}",
        f"- **Sources ({len(sections)}):**",
    ]
    for url, _ in sections:
        lines.append(f"  - {url}")

    notes = receipt.get("notes", "").strip()
    if notes:
        lines += ["", f"> {notes}"]

    lines += ["", "---", ""]

    for url, content in sections:
        lines.append(f"<!-- SOURCE: {url} -->")
        lines.append("")
        lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def write_markdown(receipt: dict, sections: list[tuple[str, str]], output_dir: Path) -> Path:
    """
    Write a timestamped .md file to output_dir and return its path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"{_safe_name(receipt['name'])}_{timestamp}.md"

    filepath.write_text(render_markdown(receipt, sections), encoding="utf-8")
    return filepath


__all__ = ["render_markdown", "write_markdown", "_safe_name"]
