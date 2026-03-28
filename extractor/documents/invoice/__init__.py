from __future__ import annotations

from importlib import import_module
from typing import Any

_INVOICE_EXPORTS = {
    "InvoiceHandler",
    "TechnicalDocumentHandler",
    "_extract_hs_last_item",
    "_extract_sparse_hs_item_without_country",
    "_extract_with_timing",
    "_extract_inline_blob_pipe_rows",
    "_trim_item_line",
    "clean_text",
    "deduplicate_items",
    "extract_structured_pipe_items",
    "load_currency_db",
    "run_invoice_extraction",
    "run_technical_document_extraction",
}

__all__ = sorted(_INVOICE_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _INVOICE_EXPORTS:
        module = import_module(".invoice", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _INVOICE_EXPORTS)
