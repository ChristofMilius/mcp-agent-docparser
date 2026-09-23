"""
misc_tools — utility tools
==========================
get_current_datetime: the model has no reliable clock; this gives it one.
doc_cache_clear: invalidate the fetch-level HTML cache.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from mcp_agent_docparser.cache import cache_clear, cache_dir, cache_enabled


def register(server, ctx) -> None:
    @server.tool()
    def get_current_datetime() -> str:
        """Return the current local and UTC date/time in ISO 8601 format."""
        now_local = datetime.now()
        return json.dumps(
            {
                "local": now_local.isoformat(),
                "utc": datetime.now(UTC).isoformat(),
                "weekday": now_local.strftime("%A"),
            },
            indent=2,
        )

    @server.tool()
    def doc_cache_clear() -> str:
        """
        Delete every entry from the fetch-level HTML cache and report what was
        removed and where. Fetched pages (static and JS-rendered) are cached on
        disk so repeat parses and crawls skip the network; call this after a
        docs site changes to force fresh fetches.
        """
        removed = cache_clear()
        return json.dumps(
            {
                "status": "ok",
                "removed": removed,
                "cache_dir": str(cache_dir()),
                "enabled": cache_enabled(),
            },
            indent=2,
        )


__all__ = ["register"]
