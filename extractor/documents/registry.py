from __future__ import annotations

from .base import DocumentDefinition, DocumentHandler

# 1. Импорты сложных документов
from .contract import (
    CMRHandler, 
    ContractHandler, 
    PowerOfAttorneyHandler,
    SupplyContractHandler, 
    TaxpayerRegistrationCardHandler,
    TrustedPassportPowerOfAttorneyHandler,
)
from .invoice import InvoiceHandler, TechnicalDocumentHandler
from .protocol import ProtocolHandler

# 2. Импорты простых документов (убедись, что эти файлы и классы созданы!)
from .passport import PassportHandler
from .export_license import ExportImportLicenseHandler
from .lab_test_report import LabTestReportHandler
from .veterinary_statement import VeterinaryStatementHandler
from .declaration_conformity import DeclarationConformityHandler
from .state_duty_payment import StateDutyPaymentHandler
from .export_conclusion import ExportConclusionHandler
from .phytosanitary import PhytosanitaryCertHandler
from .min_justice_reg import MinJusticeRegCertHandler
from .veterinary_cert import VeterinaryCertHandler
from .other_documents import OtherDocumentsHandler
from .other_information import OtherInformationHandler
from .fallback import FallbackElseHandler

def _build_definition(handler: DocumentHandler) -> DocumentDefinition:
    return DocumentDefinition(
        document_code=handler.document_code,
        label=handler.label,
        handler=handler,
        schema=handler.schema,
    )

_DOCUMENT_DEFINITIONS: dict[str, DocumentDefinition] = {}

# 3. Добавляем ВСЕ классы в массив (их тут ровно 22)
_all_handlers =[
    InvoiceHandler(),
    ContractHandler(),
    SupplyContractHandler(),
    PowerOfAttorneyHandler(),
    TrustedPassportPowerOfAttorneyHandler(),
    CMRHandler(),
    TaxpayerRegistrationCardHandler(),
    TechnicalDocumentHandler(),
    ProtocolHandler(),
    
    # Простые документы
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
]

for h in _all_handlers:
    _DOCUMENT_DEFINITIONS[h.document_code] = _build_definition(h)


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
    return[definition.to_dict() for definition in _DOCUMENT_DEFINITIONS.values()]