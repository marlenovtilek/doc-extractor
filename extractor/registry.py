from __future__ import annotations

from extractor.invoice.invoice import InvoiceHandler
from extractor.base import DocumentDefinition, DocumentHandler

def _build_definition(handler: DocumentHandler) -> DocumentDefinition:
    return DocumentDefinition(
        document_code=handler.document_code,
        label=handler.label,
        handler=handler,
        schema=handler.schema,
    )

_DOCUMENT_DEFINITIONS: dict[str, DocumentDefinition] = {}

_ALL_HANDLERS = (
    InvoiceHandler(),
)

for handler in _ALL_HANDLERS:
    _DOCUMENT_DEFINITIONS[handler.document_code] = _build_definition(handler)


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
    return list(_DOCUMENT_DEFINITIONS)


def list_document_definitions() -> list[dict[str, object]]:
    return [definition.to_dict() for definition in _DOCUMENT_DEFINITIONS.values()]


__all__ = [
    "get_document_definition",
    "get_document_handler",
    "list_document_definitions",
    "list_supported_document_codes",
]
