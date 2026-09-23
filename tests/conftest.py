"""tests/conftest.py — shared fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class FakeServer:
    """Collects tools registered via @server.tool() so we can call them."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


@pytest.fixture
def tmp_project(tmp_path: Path):
    """
    Return (root, env_dict) for a self-contained project tree: receipts.json,
    an output dir, and a logs dir, with env vars pointing at them.
    """
    root = tmp_path

    receipts = root / "receipts.json"
    receipts.write_text(json.dumps({"receipts": {}}, ensure_ascii=False), encoding="utf-8")

    env = {
        "DOCPARSER_RECEIPTS": str(receipts),
        "DOCPARSER_OUTPUT_DIR": str(root / "doc_output"),
        "DOCPARSER_LOGS_DIR": str(root / "logs"),
        "DOCPARSER_CACHE_DIR": str(root / "cache"),
    }
    return root, env


@pytest.fixture
def sample_receipt() -> dict:
    return {
        "name": "Sample SDK",
        "language": "python",
        "urls": ["https://docs.example.com/overview", "https://docs.example.com/querying"],
        "selectors": ["#content", ".prose", "article", "main", "body"],
        "strip_tags": ["nav", "footer", "header", "script", "style"],
        "section": None,
        "js_render": False,
        "markdown_passthrough": False,
        "notes": "test fixture",
        "last_fetched": None,
        "last_output": None,
    }
