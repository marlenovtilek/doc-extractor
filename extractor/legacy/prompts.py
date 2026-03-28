"""Compatibility wrapper for invoice-specific prompt constants."""

from __future__ import annotations

from ..documents.invoice.invoice_header import (
    _FOOTER_PATTERNS,
    _HEADER_PATTERNS,
    _ISO4217_NUMERIC_TO_ALPHA3,
    _ITEM_ROW_START_RE,
    _PRICE_RE,
    _TABLE_HEADER_RE,
)
from ..documents.invoice.invoice_llm import (
    EXAMPLES,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_GPT_OSS,
    _CEREBRAS_RESPONSE_FORMAT,
)
from ..documents.invoice.invoice_postprocess import _HEADER_FIELDS, _UNKNOWN_ORIGIN

__all__ = [
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
]
