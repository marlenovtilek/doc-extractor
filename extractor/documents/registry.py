from __future__ import annotations

from .base import DocumentHandler
from .invoice.handler import InvoiceHandler


_DOCUMENT_HANDLERS: dict[str, DocumentHandler] = {
    InvoiceHandler.document_code: InvoiceHandler(),
}


def get_document_handler(document_code: str) -> DocumentHandler:
    try:
        return _DOCUMENT_HANDLERS[document_code]
    except KeyError as exc:
        supported = ", ".join(sorted(_DOCUMENT_HANDLERS))
        raise ValueError(
            f"Unsupported document_code '{document_code}'. Supported document codes: {supported}."
        ) from exc


def list_supported_document_codes() -> list[str]:
    return sorted(_DOCUMENT_HANDLERS)
