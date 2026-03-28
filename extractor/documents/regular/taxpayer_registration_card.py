from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler, TRACKED_SIMPLE_DOCUMENT_FIELDS

STI025_EXTRACTION_PROMPT = """
# ROLE
You are an expert registration-document data extractor.

# TASK
You are given OCR text from a Taxpayer Registration Card STI-025. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, identifier, or INN-like registration number
- `document_date` — the date of the document
- `description` — a concise summary of the document in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

STI025_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Taxpayer Registration Card STI-025\n"
            "INN: 12345678901234\n"
            "Issued on 07.11.2024\n"
            "Registration card confirming taxpayer registration.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "12345678901234"),
            lx.data.Extraction("document_date", "07/11/2024"),
            lx.data.Extraction(
                "description",
                "Карточка регистрации налогоплательщика формы STI-025.",
            ),
        ],
    ),
]
class TaxpayerRegistrationCardHandler(ConfiguredObjectHandler):
    document_code = "000004"
    label = "Taxpayer Registration Card STI-025"
    prompt = STI025_EXTRACTION_PROMPT
    examples = tuple(STI025_EXAMPLES)
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS
    empty_error = "No STI-025 fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
