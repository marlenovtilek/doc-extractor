from __future__ import annotations

from .base import DocumentDefinition, DocumentHandler
from .invoice.handler import InvoiceHandler


_invoice_handler = InvoiceHandler()
_DOCUMENT_DEFINITIONS: dict[str, DocumentDefinition] = {
    _invoice_handler.document_code: DocumentDefinition(
        document_code=_invoice_handler.document_code,
        label=_invoice_handler.label,
        handler=_invoice_handler,
        schema=_invoice_handler.schema,
    ),
}


def get_document_definition(document_code: str) -> DocumentDefinition:
    try:
        return _DOCUMENT_DEFINITIONS[document_code]
    except KeyError as exc:
        supported = ", ".join(sorted(_DOCUMENT_DEFINITIONS))
        raise ValueError(
            f"Unsupported document_code '{document_code}'. Supported document codes: {supported}."
        ) from exc


def get_document_handler(document_code: str) -> DocumentHandler:
    return get_document_definition(document_code).handler


def list_supported_document_codes() -> list[str]:
    return sorted(_DOCUMENT_DEFINITIONS)


def list_document_definitions() -> list[dict[str, object]]:
    return [
        _DOCUMENT_DEFINITIONS[code].to_dict()
        for code in sorted(_DOCUMENT_DEFINITIONS)
    ]
