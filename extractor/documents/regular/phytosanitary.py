from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler, TRACKED_SIMPLE_DOCUMENT_FIELDS

PHYTOSANITARY_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a phytosanitary certificate in English or Russian.
The text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the certificate
- `document_date` — the date of the certificate (normalize to DD/MM/YYYY when possible)
- `description` — a concise phytosanitary certificate title in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""


class PhytosanitaryCertHandler(ConfiguredObjectHandler):
    document_code = "01207"
    label = "Phytosanitary Certificate"
    prompt = PHYTOSANITARY_PROMPT
    examples = ()
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS
    empty_error = "No Phytosanitary Certificate fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
