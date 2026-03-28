from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

TRACKED_SUPPLY_CONTRACT_FIELDS = (
    "document_number",
    "document_date",
    "description",
)

SUPPLY_CONTRACT_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Supply Contract document in English. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, identifier, or INN-like
  contract identifier when it is the only stable identifier in the document
- `document_date` — the date of the contract
- `description` — a concise summary of the contract in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

SUPPLY_CONTRACT_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "SUPPLY CONTRACT No. SUP-77/24\n"
            "Date: 14 September 2024\n"
            "This supply contract covers the delivery of industrial lubricants and spare parts.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "SUP-77/24"),
            lx.data.Extraction("document_date", "14/09/2024"),
            lx.data.Extraction(
                "description",
                "Договор поставки промышленных смазочных материалов и запасных частей.",
            ),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Supply Agreement Ref. INN-5568021\n"
            "Signed on 05/03/2025\n"
            "The contract is for supply of professional audio equipment.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "INN-5568021"),
            lx.data.Extraction("document_date", "05/03/2025"),
            lx.data.Extraction(
                "description",
                "Договор поставки профессионального аудиооборудования.",
            ),
        ],
    ),
]
class SupplyContractHandler(ConfiguredObjectHandler):
    document_code = "00012"
    label = "Supply Contract"
    prompt = SUPPLY_CONTRACT_EXTRACTION_PROMPT
    examples = tuple(SUPPLY_CONTRACT_EXAMPLES)
    tracked_fields = TRACKED_SUPPLY_CONTRACT_FIELDS
    empty_error = "No supply contract fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
