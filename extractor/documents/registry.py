from __future__ import annotations

from .invoice.invoice import InvoiceHandler
from .base import DocumentDefinition, DocumentHandler
from .regular.technical_document import TechnicalDocumentHandler
from .regular.cmr import CMRHandler
from .regular.contract import ContractHandler
from .regular.declaration_conformity import DeclarationConformityHandler
from .regular.export_conclusion import ExportConclusionHandler
from .regular.export_license import ExportImportLicenseHandler
from .regular.fallback import FallbackElseHandler
from .regular.lab_test_report import LabTestReportHandler
from .regular.min_justice_reg import MinJusticeRegCertHandler
from .regular.other_documents import OtherDocumentsHandler
from .regular.other_information import OtherInformationHandler
from .regular.passport import PassportHandler
from .regular.power_of_attorney import PowerOfAttorneyHandler
from .regular.phytosanitary import PhytosanitaryCertHandler
from .regular.protocol import ProtocolHandler
from .regular.state_duty_payment import StateDutyPaymentHandler
from .regular.supply_contract import SupplyContractHandler
from .regular.taxpayer_registration_card import TaxpayerRegistrationCardHandler
from .regular.trusted_passport_poa import TrustedPassportPowerOfAttorneyHandler
from .regular.veterinary_cert import VeterinaryCertHandler
from .regular.veterinary_statement import VeterinaryStatementHandler

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
    ContractHandler(),
    SupplyContractHandler(),
    PowerOfAttorneyHandler(),
    TrustedPassportPowerOfAttorneyHandler(),
    CMRHandler(),
    TaxpayerRegistrationCardHandler(),
    TechnicalDocumentHandler(),
    ProtocolHandler(),
    PassportHandler(),
    ExportImportLicenseHandler(),
    LabTestReportHandler(),
    VeterinaryStatementHandler(),
    DeclarationConformityHandler(),
    StateDutyPaymentHandler(),
    ExportConclusionHandler(),
    PhytosanitaryCertHandler(),
    MinJusticeRegCertHandler(),
    VeterinaryCertHandler(),
    OtherDocumentsHandler(),
    OtherInformationHandler(),
    FallbackElseHandler(),
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
