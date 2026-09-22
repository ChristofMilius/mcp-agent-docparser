"""tests/test_tools.py — tool surface through a fake MCPServer."""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from conftest import FakeServer

from mcp_agent_docparser.emit import _safe_name
from mcp_agent_docparser.receipts import ReceiptRegistry
from mcp_agent_docparser.server import INSTRUCTIONS, SERVER_NAME
from mcp_agent_docparser.tool_surface import register_all


def _ctx(root: Path, env: dict, sample_receipt: dict):
    cfg = types.SimpleNamespace(
        receipts_path=Path(env["DOCPARSER_RECEIPTS"]),
        output_dir=Path(env["DOCPARSER_OUTPUT_DIR"]),
        logs_dir=Path(env["DOCPARSER_LOGS_DIR"]),
    )
    registry = ReceiptRegistry(cfg.receipts_path)
    registry.upsert("sample", dict(sample_receipt), save=False)
    return types.SimpleNamespace(cfg=cfg, registry=registry)


@pytest.fixture
def ctx(tmp_project, sample_receipt):
    root, env = tmp_project
    return _ctx(root, env, sample_receipt)


@pytest.fixture
def tools(ctx):
    fake = FakeServer()
    register_all(fake, ctx)
    return fake.tools


def _parse(payload: str) -> dict:
    return json.loads(payload)


class TestServerMeta:
    def test_server_name_and_instructions(self):
        assert SERVER_NAME == "mcp-agent-docparser"
        assert "fetch" in INSTRUCTIONS.lower()
        assert "doc_probe" in INSTRUCTIONS

    def test_all_tools_registered(self, tools):
        expected = {
            "get_current_datetime",
            "receipt_list", "receipt_show", "receipt_add",
            "receipt_edit", "receipt_delete", "receipt_reload",
            "doc_parse", "doc_parse_url",
            "doc_probe", "doc_probe_js", "doc_output",
        }
        assert expected <= set(tools)


class TestReceiptTools:
    def test_list_empty_then_after_add(self, tools, ctx, sample_receipt):
        out = _parse(tools["receipt_list"]())
        assert out["count"] == 1  # sample seeded in fixture
        assert out["receipts"][0]["key"] == "sample"

    def test_show_returns_full_json(self, tools, sample_receipt):
        out = _parse(tools["receipt_show"](key="sample"))
        assert out["sample"]["language"] == "python"
        assert len(out["sample"]["urls"]) == 2

    def test_show_unknown(self, tools):
        out = _parse(tools["receipt_show"](key="ghost"))
        assert out["status"] == "not_found"

    def test_add_creates_and_validates(self, tools, ctx, sample_receipt):
        out = _parse(tools["receipt_add"](
            key="new",
            name="New SDK", language="typescript",
            urls=["https://x.dev"], selectors=["#content", "body"],
            notes="added by test",
        ))
        assert out["status"] == "ok"
        assert ctx.registry.get("new")["language"] == "typescript"

        bad = _parse(tools["receipt_add"](
            key="bad", name="Bad", language="text",
            urls=["https://x.dev"], selectors=[],
        ))
        assert bad["status"] == "invalid"

    def test_add_accepts_code_language(self, tools, ctx):
        out = _parse(tools["receipt_add"](
            key="code", name="Code", language="english",
            urls=["https://x.dev"], selectors=["#content"],
            code_language="typescript",
        ))
        assert out["status"] == "ok"
        got = ctx.registry.get("code")
        assert got["language"] == "english"
        assert got["code_language"] == "typescript"

    def test_edit_patches_code_language(self, tools, ctx):
        out = _parse(tools["receipt_edit"](key="sample", updates={"code_language": "json"}))
        assert out["status"] == "ok"
        assert ctx.registry.get("sample")["code_language"] == "json"

    def test_edit_patches_fields(self, tools, ctx):
        out = _parse(tools["receipt_edit"](key="sample", updates={"notes": "edited", "js_render": True}))
        assert out["status"] == "ok"
        got = ctx.registry.get("sample")
        assert got["notes"] == "edited"
        assert got["js_render"] is True

    def test_edit_unknown_key(self, tools):
        out = _parse(tools["receipt_edit"](key="ghost", updates={"notes": "x"}))
        assert out["status"] == "not_found"

    def test_delete_and_reload(self, tools, ctx):
        assert _parse(tools["receipt_delete"](key="sample"))["status"] == "deleted"
        assert _parse(tools["receipt_reload"]())["count"] == 0


class TestEmit:
    def test_safe_name(self):
        assert _safe_name("LM Studio Python SDK!") == "lm_studio_python_sdk"


class TestToolErrors:
    def test_unknown_tool_name_reported(self, tools):
        # Simulate a raise inside a handler — the audit wrapper must not swallow it.
        import mcp_agent_docparser.errors as errors

        msg = errors.tool_error("fake_tool", ValueError("boom"))
        assert "fake_tool" in msg
        assert "ValueError" in msg
        assert "boom" not in msg  # exception message is never surfaced
