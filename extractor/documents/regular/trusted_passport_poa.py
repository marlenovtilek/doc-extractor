from __future__ import annotations

import langextract as lx

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

TRACKED_TRUSTED_PASSPORT_POA_FIELDS = (
    "document_number",
    "authorized_person",
    "trusted_person",
    "document_date",
    "description",
)

TRUSTED_PASSPORT_POA_EXTRACTION_PROMPT = """
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
- `description` — document type; when passport details of a natural person are
  present in the text, use `Power of Attorney with trusted persons passport`

# RULES
- Ignore headers, footers, signatures, stamps, and legal boilerplate not related
  to the requested fields.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- If `document_date` is not found, default it to the current date.
- Return only relevant extractions.
"""

TRUSTED_PASSPORT_POA_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "POWER OF ATTORNEY No. TP-14/2025\n"
            "Issued on 21/01/2025\n"
            "Aizada Toktorova authorizes Bekzat Imanov to act on her behalf.\n"
            "Passport No. AN1234567 issued to Bekzat Imanov.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "TP-14/2025"),
            lx.data.Extraction("authorized_person", "Bekzat Imanov"),
            lx.data.Extraction("trusted_person", "Aizada Toktorova"),
            lx.data.Extraction("document_date", "21/01/2025"),
            lx.data.Extraction("description", "Power of Attorney with trusted persons passport"),
        ],
    ),
]
class TrustedPassportPowerOfAttorneyHandler(ConfiguredObjectHandler):
    document_code = "000011"
    label = "PA with Trusted Persons Passport"
    prompt = TRUSTED_PASSPORT_POA_EXTRACTION_PROMPT
    examples = tuple(TRUSTED_PASSPORT_POA_EXAMPLES)
    tracked_fields = TRACKED_TRUSTED_PASSPORT_POA_FIELDS
    default_current_date_if_missing = True
    empty_error = "No power of attorney with trusted persons passport fields extracted"

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
