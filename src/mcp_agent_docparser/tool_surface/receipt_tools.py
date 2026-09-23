"""
receipt_tools — receipt registry management
===========================================
Mirrors the terminal-menu docparser's receipt commands (-add / -edit /
-delete / -reload / -list / -show / -export / -import) as MCP tools.

All mutations go through ReceiptRegistry so receipts.json stays in sync.
"""

from __future__ import annotations

import json

from mcp_agent_docparser.errors import tool_error


def register(server, ctx) -> None:
    registry = ctx.registry

    @server.tool()
    def receipt_list() -> str:
        """List all registered receipts with key, language, and last-fetch status."""
        try:
            data = registry.all()
            items = []
            for key, rec in sorted(data.items()):
                urls = rec.get("urls", [])
                items.append({
                    "key": key,
                    "name": rec.get("name", key),
                    "language": rec.get("language", "text"),
                    "url_count": len(urls),
                    "first_url": urls[0] if urls else None,
                    "js_render": rec.get("js_render", False),
                    "last_fetched": rec.get("last_fetched"),
                    "last_output": rec.get("last_output"),
                })
            return json.dumps({"count": len(items), "receipts": items}, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("receipt_list", e)

    @server.tool()
    def receipt_show(key: str) -> str:
        """Show the full JSON of a single receipt by its key."""
        try:
            receipt = registry.get(key)
            if receipt is None:
                return json.dumps({"status": "not_found", "key": key})
            return json.dumps({key: receipt}, indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("receipt_show", e)

    @server.tool()
    def receipt_add(
        key: str,
        name: str,
        language: str,
        urls: list[str],
        selectors: list[str],
        strip_tags: list[str] | None = None,
        section: str | None = None,
        js_render: bool = False,
        markdown_passthrough: bool = False,
        notes: str = "",
        code_language: str | None = None,
        js_settle_ms: int | None = None,
    ) -> str:
        """
        Create a new receipt (or replace an existing one).

        Required: key, name, language, urls, selectors. Optional: strip_tags,
        section, js_render, markdown_passthrough, notes, code_language,
        js_settle_ms.
        Validates before writing; returns validation errors if the receipt is
        malformed.

        `language` is the human language of the documentation. `code_language`
        optionally overrides the ``` fence language when the page's blocks are
        in another language (e.g. a React SDK doc in English that emits
        TypeScript). When omitted, the fence language is auto-detected from the
        page and falls back to `language` only if it names a code language.

        `js_settle_ms` tunes the Playwright hydration delay (ms) before the
        "Copy as Markdown" button is probed for, for late-hydrating sites.
        """
        try:
            receipt = {
                "name": name,
                "language": language,
                "urls": urls,
                "selectors": selectors,
                "strip_tags": strip_tags,
                "section": section,
                "js_render": js_render,
                "markdown_passthrough": markdown_passthrough,
                "notes": notes,
                "code_language": code_language,
                "js_settle_ms": js_settle_ms,
                "last_fetched": None,
                "last_output": None,
            }
            errors = registry.upsert(key, receipt)
            if errors:
                return json.dumps({"status": "invalid", "key": key, "errors": errors}, indent=2)
            saved = registry.get(key)
            return json.dumps({"status": "ok", "key": key, "saved": {k: saved[k] for k in
                              ("name", "language", "urls", "selectors", "js_render",
                               "markdown_passthrough", "js_settle_ms")}},
                              indent=2, ensure_ascii=False)
        except Exception as e:
            return tool_error("receipt_add", e)

    @server.tool()
    def receipt_edit(key: str, updates: dict) -> str:
        """
        Patch specific fields of an existing receipt.

        `updates` is a JSON object of field → value. Allowed fields: name,
        language, urls, selectors, strip_tags, section, js_render,
        markdown_passthrough, notes, code_language. Returns false if the key
        does not exist.
        """
        try:
            allowed = {"name", "language", "urls", "selectors", "strip_tags",
                   "section", "js_render", "markdown_passthrough", "notes",
                   "code_language", "js_settle_ms"}
            fields = {k: v for k, v in updates.items() if k in allowed}
            if not fields:
                return json.dumps({"status": "no_fields", "allowed": sorted(allowed)}, indent=2)
            ok = registry.update_fields(key, fields)
            if not ok:
                return json.dumps({"status": "not_found", "key": key})
            return json.dumps({"status": "ok", "key": key, "updated": sorted(fields)}, indent=2)
        except Exception as e:
            return tool_error("receipt_edit", e)

    @server.tool()
    def receipt_delete(key: str) -> str:
        """Delete a receipt by key. Returns false if the key does not exist."""
        try:
            existed = registry.delete(key)
            return json.dumps({"status": "deleted" if existed else "not_found", "key": key}, indent=2)
        except Exception as e:
            return tool_error("receipt_delete", e)

    @server.tool()
    def receipt_reload() -> str:
        """Re-read receipts.json from disk (pick up external edits)."""
        try:
            registry.reload()
            return json.dumps({"status": "ok", "count": len(registry.keys())}, indent=2)
        except Exception as e:
            return tool_error("receipt_reload", e)


__all__ = ["register"]
