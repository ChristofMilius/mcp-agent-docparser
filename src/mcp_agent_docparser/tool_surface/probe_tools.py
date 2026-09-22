"""
probe_tools — discovery tools
=============================
doc_probe / doc_probe_js: discover which CSS selectors match an unknown page.
doc_output: inspect the emitted .md files in the output directory.
"""

from __future__ import annotations

import json

from mcp_agent_docparser.errors import tool_error
from mcp_agent_docparser.probe import probe_url, probe_url_js


def register(server, ctx) -> None:
    output_dir = ctx.cfg.output_dir

    @server.tool()
    def doc_probe(url: str) -> str:
        """
        Probe a documentation page to discover its selector structure.

        Fetches the URL statically and reports which candidate CSS selectors
        match, the H2 section structure, and sample internal links. The
        findings' best_selector can be used to create a new receipt.
        """
        try:
            findings = probe_url(url)
            if findings is None:
                return json.dumps({"status": "fetch_failed", "url": url}, indent=2)
            return json.dumps({"status": "ok", **findings}, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("doc_probe", e)

    @server.tool()
    def doc_probe_js(url: str) -> str:
        """
        Probe a JS-rendered documentation page via headless Chromium.

        Same selector report as doc_probe, but over the rendered DOM, plus
        detection of a 'Copy as Markdown' button (a saved receipt then
        pre-fills js_render and markdown_passthrough). Requires Playwright
        Chromium installed.
        """
        try:
            findings = probe_url_js(url)
            if findings is None:
                return json.dumps({"status": "fetch_failed", "url": url}, indent=2)
            return json.dumps({"status": "ok", **findings}, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("doc_probe_js", e)

    @server.tool()
    def doc_output() -> str:
        """List the extracted .md files currently in the output directory."""
        try:
            if not output_dir.exists():
                return json.dumps({"status": "ok", "output_dir": str(output_dir), "files": []}, indent=2)
            files = []
            for f in sorted(output_dir.glob("*.md")):
                files.append({"filename": f.name, "bytes": f.stat().st_size})
            return json.dumps({
                "status": "ok",
                "output_dir": str(output_dir),
                "count": len(files),
                "files": files,
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("doc_output", e)


__all__ = ["register"]
