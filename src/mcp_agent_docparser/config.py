"""
config.py — All configuration in one place
==========================================
Loads from environment variables. No secrets involved.

Path resolution:
  - All path fields are resolved to absolute paths at construction time.
  - Relative values (DOCPARSER_RECEIPTS, DOCPARSER_OUTPUT_DIR) are resolved
    relative to the project root (the directory containing the package),
    NOT the process CWD. Agent harnesses set an unpredictable CWD when
    spawning MCP server subprocesses.
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root — the directory containing the package (src/mcp_agent_docparser).
# All relative path env vars are resolved against this, never against CWD.
_BASE = Path(__file__).resolve().parent.parent.parent


def _resolve_path(raw: str) -> Path:
    """
    Resolve a path string to an absolute path.

    If the value from the environment is already absolute, return it
    normalized. If relative, resolve relative to the project root (_BASE),
    not the process CWD.
    """
    p = Path(raw)
    if p.is_absolute():
        return p
    return (_BASE / p).resolve()


class Config:
    def __init__(self) -> None:
        self.receipts_path: Path = _resolve_path(
            os.getenv("DOCPARSER_RECEIPTS", "receipts.json")
        )
        self.output_dir: Path = _resolve_path(
            os.getenv("DOCPARSER_OUTPUT_DIR", "doc_output")
        )
        self.logs_dir: Path = _resolve_path(
            os.getenv("DOCPARSER_LOGS_DIR", "logs")
        )
        self.cache_dir: Path = _resolve_path(
            os.getenv("DOCPARSER_CACHE_DIR", "cache")
        )
        self.cache_ttl_seconds: float = _env_float("DOCPARSER_CACHE_TTL_SECONDS", 0.0)

    def __repr__(self) -> str:
        return (
            f"Config("
            f"receipts_path={self.receipts_path!r}, "
            f"output_dir={self.output_dir!r}, "
            f"logs_dir={self.logs_dir!r}, "
            f"cache_dir={self.cache_dir!r}, "
            f"cache_ttl_seconds={self.cache_ttl_seconds!r}, "
            f")"
        )


def _env_float(name: str, default: float) -> float:
    """Parse a float env var, falling back to `default` on junk values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


__all__ = ["Config"]
