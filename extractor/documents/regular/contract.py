from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

TRACKED_CONTRACT_FIELDS = (
    "document_number",
    "document_date",
    "parties",
    "subject",
    "description",
)

CONTRACT_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Contract document in English. The text may have mixed
formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the contract
- `document_date` — the date of the contract
- `parties` — the parties involved; emit one extraction per party
- `subject` — the subject, object, or purpose of the contract
- `description` — a concise summary of the contract in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and decorative boilerplate.
- Normalize dates when possible.
- Remove formatting artifacts mentally; do not copy broken punctuation unless it is
  part of an actual identifier.
- If a field cannot be found, do not hallucinate it.
- For `parties`, emit separate extractions of class `parties` for each party.
- Return only relevant extractions.
"""

CONTRACT_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "CONTRACT No. CT-2024/117\n"
            "Date: 12 November 2024\n"
            "This contract is made between Acme GmbH, Germany and Global Tech LLC, Kyrgyz Republic.\n"
            "Subject: Supply of industrial spare parts.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "CT-2024/117"),
            lx.data.Extraction("document_date", "12/11/2024"),
            lx.data.Extraction("parties", "Acme GmbH"),
            lx.data.Extraction("parties", "Global Tech LLC"),
            lx.data.Extraction("subject", "Supply of industrial spare parts"),
            lx.data.Extraction(
                "description",
                "Контракт на поставку промышленных запасных частей между Acme GmbH и Global Tech LLC.",
            ),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Agreement Ref. SC-88/25\n"
            "Signed on 05/03/2025\n"
            "Parties: Sennheiser Middle East FZE (Seller) and OOO Global Tech (Buyer).\n"
            "The purpose of this contract is the sale and delivery of professional audio equipment.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "SC-88/25"),
            lx.data.Extraction("document_date", "05/03/2025"),
            lx.data.Extraction("parties", "Sennheiser Middle East FZE"),
            lx.data.Extraction("parties", "OOO Global Tech"),
            lx.data.Extraction("subject", "Sale and delivery of professional audio equipment"),
            lx.data.Extraction(
                "description",
                "Контракт на продажу и поставку профессионального аудиооборудования.",
            ),
        ],
    ),
]


class ContractHandler(ConfiguredObjectHandler):
    document_code = "03011"
    label = "Contract"
    prompt = CONTRACT_EXTRACTION_PROMPT
    examples = tuple(CONTRACT_EXAMPLES)
    tracked_fields = TRACKED_CONTRACT_FIELDS
    array_fields = ("parties",)
    empty_error = "No contract fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("parties", "Parties", kind="array"),
            DocumentFieldSchema("subject", "Subject"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
