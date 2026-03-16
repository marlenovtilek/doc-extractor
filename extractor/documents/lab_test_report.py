from .simple_base import BaseSimpleDocumentHandler

class LabTestReportHandler(BaseSimpleDocumentHandler):
    document_code = "11111"
    label = "Laboratory Test Report"
    # Переопределяем инструкцию только для этого документа
    desc_instruction = "The description must contain only the document title (without numbers, dates, or identifiers, 1–2 sentences, **keep in Russian**)."