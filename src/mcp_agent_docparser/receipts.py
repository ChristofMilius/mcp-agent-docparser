"""
receipts.py — Receipt registry (load / save / validate)
========================================================
Ported from the terminal-menu docparser: a thin wrapper around a JSON file
that keeps an in-memory dict read from / written to disk on demand. All
mutations go through this class so the file stays in sync.

The original CLI used ANSI print helpers; server mode routes through the
logging module instead so stdio (the MCP transport) stays clean.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

#: Required keys every receipt must have.
_REQUIRED_KEYS: set[str] = {"name", "language", "urls", "selectors"}

#: Keys that are managed automatically and should always be present after normalisation.
_AUTO_KEYS: dict[str, object] = {
    "strip_tags":           [],
    "section":              None,
    "js_render":            False,
    "markdown_passthrough": False,
    "notes":                "",
    "last_fetched":         None,
    "last_output":          None,
}


def _normalise_receipt(raw: dict) -> dict:
    """Fill in optional keys with their defaults so callers can always rely on them."""
    receipt = dict(raw)
    for key, default in _AUTO_KEYS.items():
        receipt.setdefault(key, default)
    return receipt


def _validate_receipt(key: str, receipt: dict) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []
    for k in _REQUIRED_KEYS:
        if k not in receipt:
            errors.append(f"missing required field '{k}'")
    if "urls" in receipt and not isinstance(receipt["urls"], list):
        errors.append("'urls' must be a list")
    elif "urls" in receipt and not receipt["urls"]:
        errors.append("'urls' must not be empty")
    if "selectors" in receipt and not isinstance(receipt["selectors"], list):
        errors.append("'selectors' must be a list")
    elif "selectors" in receipt and not receipt["selectors"]:
        errors.append("'selectors' must not be empty")
    return errors


class ReceiptRegistry:
    """
    Thin wrapper around receipts.json.

    Keeps an in-memory dict that is read from / written to disk on demand.
    All mutations go through this class so the file stays in sync.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read receipts.json from disk, creating an empty registry if absent."""
        if not self.path.exists():
            logger.warning("Receipts file not found at %s — starting with empty registry.", self.path)
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            receipts_block = raw.get("receipts", raw)   # tolerate bare dict
            self._data = {k: _normalise_receipt(v) for k, v in receipts_block.items()}
            logger.info("Loaded %d receipt(s) from %s", len(self._data), self.path)
        except json.JSONDecodeError as exc:
            logger.error("Could not parse %s: %s", self.path, exc)
            self._data = {}

    def save(self) -> None:
        """Persist in-memory registry to disk, preserving schema_version and comment."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment":        "docparser receipt registry — edit this file to add/update/remove receipts",
            "_schema_version": "2",
            "receipts":        self._data,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %d receipt(s) to %s", len(self._data), self.path)

    def reload(self) -> None:
        """Re-read from disk (useful after an external editor session)."""
        self._load()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def keys(self) -> list[str]:
        return sorted(self._data.keys())

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def all(self) -> dict[str, dict]:
        return dict(self._data)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def upsert(self, key: str, receipt: dict, *, save: bool = True) -> list[str]:
        """
        Insert or replace a receipt.  Validates before writing.
        Returns a list of validation errors (empty = success).
        """
        errors = _validate_receipt(key, receipt)
        if errors:
            return errors
        self._data[key] = _normalise_receipt(receipt)
        if save:
            self.save()
        return []

    def delete(self, key: str, *, save: bool = True) -> bool:
        """Remove a receipt by key.  Returns True if it existed."""
        existed = key in self._data
        if existed:
            del self._data[key]
            if save:
                self.save()
        return existed

    def update_fields(self, key: str, fields: dict, *, save: bool = True) -> bool:
        """Patch specific fields of an existing receipt.  Returns False if key missing."""
        if key not in self._data:
            return False
        self._data[key].update(fields)
        if save:
            self.save()
        return True

    def mark_fetched(self, key: str, output_filename: str) -> None:
        """Record a successful parse — update last_fetched and last_output."""
        logger.info("Marking receipt '%s' as fetched → %s", key, output_filename)
        self.update_fields(key, {
            "last_fetched": date.today().isoformat(),
            "last_output":  output_filename,
        })


__all__ = [
    "ReceiptRegistry",
    "_normalise_receipt",
    "_validate_receipt",
    "_REQUIRED_KEYS",
    "_AUTO_KEYS",
]
