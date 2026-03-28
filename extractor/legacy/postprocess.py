"""Compatibility wrapper for invoice-specific postprocessing helpers."""

from __future__ import annotations

from typing import Any

from ..documents.invoice.invoice_llm import _repair_json, validate_and_parse
from ..documents.invoice.invoice_parser import extract_structured_pipe_items
from ..documents.invoice.invoice_postprocess import (
    deduplicate_items,
    filter_ocr_anomalies,
    post_fill_from_header as _post_fill_from_header,
    sort_items_by_position,
    spread_single_country_origin,
)
from ..normalizers.currency import load_currency_db

__all__ = [
    "_repair_json",
    "validate_and_parse",
    "post_fill_from_header",
    "spread_single_country_origin",
    "deduplicate_items",
    "filter_ocr_anomalies",
    "extract_structured_pipe_items",
    "sort_items_by_position",
]


def post_fill_from_header(items: list[dict], header_meta: dict) -> list[dict]:
    return _post_fill_from_header(items, header_meta, load_currency_db())
