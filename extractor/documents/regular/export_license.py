from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler, TRACKED_SIMPLE_DOCUMENT_FIELDS

EXPORT_IMPORT_LICENSE_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from an export or import license in English or Russian.
The text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the document
- `document_date` — the date of the document (normalize to DD/MM/YYYY when possible)
- `description` — a concise description of the export or import license in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""


class ExportImportLicenseHandler(ConfiguredObjectHandler):
    document_code = "01011"
    label = "EXPORT/IMPORT License"
    prompt = EXPORT_IMPORT_LICENSE_PROMPT
    examples = ()
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS
    empty_error = "No EXPORT/IMPORT License fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
