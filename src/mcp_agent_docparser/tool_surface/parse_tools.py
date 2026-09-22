"""
parse_tools — doc parsing tools
===============================
doc_parse: run the full pipeline (fetch → extract → emit) for a saved receipt.
doc_parse_url: fetch an arbitrary URL using a saved receipt as a selector template.
"""

from __future__ import annotations

import json

from mcp_agent_docparser.emit import render_markdown, write_markdown
from mcp_agent_docparser.errors import tool_error
from mcp_agent_docparser.extract import extract_content
from mcp_agent_docparser.fetch import fetch
from mcp_agent_docparser.parse import parse_receipt


def register(server, ctx) -> None:
    registry = ctx.registry
    output_dir = ctx.cfg.output_dir

    @server.tool()
    def doc_parse(key: str, dry_run: bool = False) -> str:
        """
        Parse a saved receipt: fetch all its URLs, extract the content,
        and write a timestamped .md file into the output directory.

        Returns the emitted filename plus a per-URL character count and the
        full rendered markdown. With dry_run=true, reports what would be
        fetched without making any network requests.
        """
        try:
            result = parse_receipt(key, registry, output_dir, dry_run=dry_run)
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("doc_parse", e)

    @server.tool()
    def doc_parse_url(key: str, url: str) -> str:
        """
        Parse an arbitrary URL using an existing receipt as a template for its
        selectors/strip_tags/language. Does not persist the result as a receipt.

        Returns the emitted filename and the rendered markdown.
        """
        try:
            receipt = registry.get(key)
            if receipt is None:
                return json.dumps({"status": "not_found", "key": key}, indent=2)

            # Build a throwaway receipt — do not persist it.
            template = dict(receipt)
            template["name"] = f"Custom — {url[:60]}"
            template["urls"] = [url]

            soup = fetch(url, js_render=template.get("js_render", False))
            if soup is None:
                return json.dumps({"status": "fetch_failed", "url": url}, indent=2)

            content = extract_content(soup, template)
            filepath = write_markdown(template, [(url, content)], output_dir)

            return json.dumps({
                "status": "ok",
                "template": key,
                "url": url,
                "output_dir": str(output_dir),
                "output_filename": filepath.name,
                "chars": len(content),
                "markdown": render_markdown(template, [(url, content)]),
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("doc_parse_url", e)


__all__ = ["register"]
