from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

TRACKED_POWER_OF_ATTORNEY_FIELDS = (
    "document_number",
    "authorized_person",
    "trusted_person",
    "document_date",
    "description",
)

POWER_OF_ATTORNEY_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Power of Attorney (POA) document in English. The
text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the numbering or reference number of the POA
- `authorized_person` — full name of the person who is authorized to act
- `trusted_person` — full name of the person who issued the POA or grants the authority
- `document_date` — the date of the POA
- `description` — the type of document, keep it in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and legal boilerplate not related
  to the requested fields.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- If `document_date` is not found, default it to the current date.
- Return only relevant extractions.
"""

POWER_OF_ATTORNEY_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "POWER OF ATTORNEY No. POA-22/2025\n"
            "Date: 03 February 2025\n"
            "Global Tech LLC hereby authorizes Aibek Omuraliev to represent the company.\n"
            "Granted by Dinara Sadykova, General Director.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "POA-22/2025"),
            lx.data.Extraction("authorized_person", "Aibek Omuraliev"),
            lx.data.Extraction("trusted_person", "Dinara Sadykova"),
            lx.data.Extraction("document_date", "03/02/2025"),
            lx.data.Extraction("description", "Доверенность"),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Special Power of Attorney\n"
            "Issued on 18/10/2024\n"
            "Acme GmbH appoints Elena Petrova as authorized representative.\n"
            "Signed by Markus Klein.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", None),
            lx.data.Extraction("authorized_person", "Elena Petrova"),
            lx.data.Extraction("trusted_person", "Markus Klein"),
            lx.data.Extraction("document_date", "18/10/2024"),
            lx.data.Extraction("description", "Доверенность"),
        ],
    ),
]
class PowerOfAttorneyHandler(ConfiguredObjectHandler):
    document_code = "11019"
    label = "Power of Attorney"
    prompt = POWER_OF_ATTORNEY_EXTRACTION_PROMPT
    examples = tuple(POWER_OF_ATTORNEY_EXAMPLES)
    tracked_fields = TRACKED_POWER_OF_ATTORNEY_FIELDS
    default_current_date_if_missing = True
    empty_error = "No power of attorney fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("authorized_person", "Authorized Person"),
            DocumentFieldSchema("trusted_person", "Trusted Person"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
