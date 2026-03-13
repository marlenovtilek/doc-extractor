"""Compatibility wrapper for invoice-specific prompt constants."""

from __future__ import annotations

from importlib import import_module


_EXPORTED_NAMES = {
    "EXAMPLES",
    "EXTRACTION_PROMPT",
    "EXTRACTION_PROMPT_GPT_OSS",
    "_CEREBRAS_RESPONSE_FORMAT",
    "_FOOTER_PATTERNS",
    "_HEADER_FIELDS",
    "_HEADER_PATTERNS",
    "_ISO4217_NUMERIC_TO_ALPHA3",
    "_ITEM_ROW_START_RE",
    "_PRICE_RE",
    "_TABLE_HEADER_RE",
    "_UNKNOWN_ORIGIN",
}


def _invoice_module():
    return import_module(".documents.invoice", __package__)


def __getattr__(name: str):
    if name in _EXPORTED_NAMES:
        return getattr(_invoice_module(), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_EXPORTED_NAMES))
