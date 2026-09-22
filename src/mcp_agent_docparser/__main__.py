"""
`python -m mcp_agent_docparser` — runs the MCP server (stdio transport by default).
"""

from __future__ import annotations

import sys

from mcp_agent_docparser.cli import main

if __name__ == "__main__":
    sys.exit(main())
