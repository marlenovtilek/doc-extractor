"""Compatibility wrapper for invoice-specific postprocessing helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def _invoice_module():
    return import_module(".documents.invoice", __package__)


def _repair_json(raw_text: str) -> str:
    return _invoice_module()._repair_json(raw_text)


def validate_and_parse(raw_text: str) -> dict[str, Any]:
    return _invoice_module().validate_and_parse(raw_text)


def post_fill_from_header(items: list[dict], header_meta: dict) -> list[dict]:
    return _invoice_module().post_fill_from_header(items, header_meta)


def spread_single_country_origin(items: list[dict]) -> list[dict]:
    return _invoice_module().spread_single_country_origin(items)


def deduplicate_items(items: list[dict]) -> list[dict]:
    return _invoice_module().deduplicate_items(items)


def filter_ocr_anomalies(items: list[dict]) -> list[dict]:
    return _invoice_module().filter_ocr_anomalies(items)


def extract_structured_pipe_items(context: str) -> list[dict]:
    return _invoice_module().extract_structured_pipe_items(context)


def sort_items_by_position(items: list[dict]) -> list[dict]:
    return _invoice_module().sort_items_by_position(items)
