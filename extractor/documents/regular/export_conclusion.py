from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler, TRACKED_SIMPLE_DOCUMENT_FIELDS

EXPORT_CONCLUSION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from an export conclusion document in English or Russian.
The text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the document
- `document_date` — the date of the document (normalize to DD/MM/YYYY when possible)
- `description` — a concise description of the export conclusion in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""


class ExportConclusionHandler(ConfiguredObjectHandler):
    document_code = "010000"
    label = "Export Conclusion"
    prompt = EXPORT_CONCLUSION_PROMPT
    examples = ()
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS
    empty_error = "No Export Conclusion fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
