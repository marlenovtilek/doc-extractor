from __future__ import annotations

from .base import DocumentDefinition, DocumentHandler
from .contract import (
    CMRHandler,
    ContractHandler,
    PowerOfAttorneyHandler,
    SupplyContractHandler,
    TaxpayerRegistrationCardHandler,
    TrustedPassportPowerOfAttorneyHandler,
)
from .invoice import InvoiceHandler, TechnicalDocumentHandler


def _build_definition(handler: DocumentHandler) -> DocumentDefinition:
    return DocumentDefinition(
        document_code=handler.document_code,
        label=handler.label,
        handler=handler,
        schema=handler.schema,
    )


_invoice_handler = InvoiceHandler()
_contract_handler = ContractHandler()
_supply_contract_handler = SupplyContractHandler()
_power_of_attorney_handler = PowerOfAttorneyHandler()
_trusted_passport_poa_handler = TrustedPassportPowerOfAttorneyHandler()
_cmr_handler = CMRHandler()
_sti025_handler = TaxpayerRegistrationCardHandler()
_technical_document_handler = TechnicalDocumentHandler()
_DOCUMENT_DEFINITIONS: dict[str, DocumentDefinition] = {
    _invoice_handler.document_code: _build_definition(_invoice_handler),
    _contract_handler.document_code: _build_definition(_contract_handler),
    _supply_contract_handler.document_code: _build_definition(_supply_contract_handler),
    _power_of_attorney_handler.document_code: _build_definition(_power_of_attorney_handler),
    _trusted_passport_poa_handler.document_code: _build_definition(_trusted_passport_poa_handler),
    _cmr_handler.document_code: _build_definition(_cmr_handler),
    _sti025_handler.document_code: _build_definition(_sti025_handler),
    _technical_document_handler.document_code: _build_definition(_technical_document_handler),
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
    return list(_DOCUMENT_DEFINITIONS)


def list_document_definitions() -> list[dict[str, object]]:
    return [definition.to_dict() for definition in _DOCUMENT_DEFINITIONS.values()]
