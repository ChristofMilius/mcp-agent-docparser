"""
cli.py — command-line interface
================================
Subcommands:
  serve    Run the MCP server (default). --http switches to streamable-http.
  doctor   Offline diagnostics (paths, registry state, emitted files).

The CLI mirrors the mail sibling's shape. It is the operator console, not the
model-facing surface; output only reports paths/state, no secrets.
"""

from __future__ import annotations

import argparse
import sys

from mcp_agent_docparser import __version__


def _cmd_serve(args) -> int:
    from mcp_agent_docparser.server import run

    transport = "streamable-http" if args.http else "stdio"
    try:
        run(transport=transport, host=args.host, port=args.port)
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_doctor(args) -> int:
    from mcp_agent_docparser.config import Config
    from mcp_agent_docparser.receipts import ReceiptRegistry

    print(f"mcp-agent-docparser {__version__} — doctor\n")

    try:
        cfg = Config()
    except Exception as e:
        print(f"[config] {type(e).__name__}: {e}")
        return 1

    print(f"  receipts : {cfg.receipts_path}")
    print(f"  output   : {cfg.output_dir}")
    print(f"  logs     : {cfg.logs_dir}")

    registry = ReceiptRegistry(cfg.receipts_path)
    print(f"\n  Receipts in registry: {len(registry.keys())}")
    for key in registry.keys():
        rec = registry.get(key)
        print(f"    {key:30s}  {rec['language']:12s}  urls={len(rec.get('urls', []))}")

    print(f"\n  Emitted files in {cfg.output_dir}:")
    if cfg.output_dir.exists():
        files = sorted(cfg.output_dir.glob("*.md"))
        for f in files:
            print(f"    {f.name}  ({f.stat().st_size:,} bytes)")
        if not files:
            print("    (none yet)")
    else:
        print("    (directory does not exist yet — created on first parse)")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-agent-docparser",
        description="MCP server for the docparser pipeline — fetch → extract → emit SDK docs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Run the MCP server (default).")
    p_serve.add_argument("--http", action="store_true", help="Use streamable-http transport.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=_cmd_serve)

    p_doc = sub.add_parser("doctor", help="Diagnose configuration and registry state.")
    p_doc.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        # Default action: serve over stdio (what MCP harnesses expect).
        args.http = False
        args.host = "127.0.0.1"
        args.port = 8000
        return _cmd_serve(args)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["build_parser", "main"]
