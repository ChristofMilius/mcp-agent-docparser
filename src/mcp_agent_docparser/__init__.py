"""
mcp_agent_docparser — MCP server wrapping the docparser pipeline
=================================================================
fetch → extract → emit  SDK documentation as clean markdown.

Ported from the terminal-menu docparser; the interactive REPL commands became
MCP tools: receipt management, parse, and probe are now callable by any
MCP-aware agent harness over stdio.

Receipts live in receipts.json next to the project root and are never
hard-coded in the Python source.
"""

from __future__ import annotations

__version__ = "0.1.0"


def main() -> int:
    """Console entry point (`mcp-agent-docparser`). Dispatches to the CLI."""
    from mcp_agent_docparser.cli import main as _cli_main

    return _cli_main()


__all__ = ["__version__", "main"]
