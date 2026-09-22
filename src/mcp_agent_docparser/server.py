"""
server.py — MCP server assembly
===============================
Wires Config → registry into an AppContext, builds an MCPServer, and
registers the tool surface.

Uses mcp 2.x (`mcp.server.mcpserver.MCPServer`).
"""

from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer

from mcp_agent_docparser import __version__
from mcp_agent_docparser.config import Config
from mcp_agent_docparser.context import AppContext
from mcp_agent_docparser.logging_setup import setup_logging
from mcp_agent_docparser.receipts import ReceiptRegistry
from mcp_agent_docparser.tool_surface import register_all

logger = logging.getLogger(__name__)

SERVER_NAME = "mcp-agent-docparser"

INSTRUCTIONS = """
SDK documentation extractor. Fetches documentation pages, strips navigation
noise, converts HTML to clean markdown, and writes timestamped .md files.

Pipeline: fetch → extract → emit.

Receipts describe how to fetch and extract a documentation site. They live in
receipts.json and can be created with receipt_add, edited with receipt_edit,
and listed with receipt_list.

Workflow for a new site:
  1. doc_probe (or doc_probe_js for JS-rendered pages) → discover the page's
     selectors and H2 structure.
  2. receipt_add → save the findings as a receipt (best_selector plus any
     strip_tags / js_render / markdown_passthrough tweaks).
  3. doc_parse → generate the .md output and get the rendered markdown back.
     Use dry_run=true first to see what will be fetched.
  Unfamiliar single pages that match an existing receipt's templates can be
  parsed directly with doc_parse_url without saving a receipt.
""".strip()


def build_context() -> AppContext:
    """Construct the full application object graph."""
    cfg = Config()
    setup_logging(str(cfg.logs_dir))

    registry = ReceiptRegistry(cfg.receipts_path)
    return AppContext(cfg=cfg, registry=registry)


def create_server(ctx: AppContext | None = None) -> MCPServer:
    """Build an MCPServer with the full tool surface registered."""
    if ctx is None:
        ctx = build_context()

    server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)
    register_all(server, ctx)

    logger.info(
        "[server] %s v%s ready (receipts=%s, output=%s)",
        SERVER_NAME, __version__, ctx.cfg.receipts_path, ctx.cfg.output_dir,
    )
    return server


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> None:
    """Build and run the server.

    transport: "stdio" (default), "sse", or "streamable-http".
    """
    server = create_server()
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=transport, host=host, port=port)


__all__ = ["SERVER_NAME", "build_context", "create_server", "run"]
