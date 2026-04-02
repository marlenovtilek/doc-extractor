from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

CMR_EXTRACTION_PROMPT = """
# ROLE
You are an expert logistics-document data extractor.

# TASK
You are given OCR text from a CMR document. The text may have mixed formats,
irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the CMR
- `document_date` — the date of the document
- `description` — a concise summary of the document in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

CMR_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "CMR No. 442190\n"
            "Date: 18/09/2025\n"
            "International consignment note for delivery of industrial equipment from Germany to Kyrgyzstan.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "442190"),
            lx.data.Extraction("document_date", "18/09/2025"),
            lx.data.Extraction(
                "description",
                "Международная транспортная накладная CMR на перевозку промышленного оборудования.",
            ),
        ],
    ),
]

class CMRHandler(ConfiguredObjectHandler):
    document_code = "00002"
    label = "CMR"
    desc_instruction = "Краткое описание CMR накладной на русском языке."

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
