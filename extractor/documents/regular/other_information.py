from __future__ import annotations

from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler

OTHER_INFO_PROMPT = """
# ROLE
You are an expert legal-document data extractor specialized in Russian official requests and customs applications.
You are given the text of a document, which may have mixed formats, irregular structure, and inconsistent spacing.
Your task is to extract structured data as accurately as possible.

# EXTRACT THE FOLLOWING FIELDS:
- `document_number` — The official number, reference, or identifier of the document (look for "Исх. №", "Ref No"). If you recognized no document_number, then just write "Б/Н".
- `document_date` — The date of the document (normalize to DD.MM.YYYY if possible).
- `hs_code` — The Customs Commodity Code (look for "ТН ВЭД", "код"). Extract digits only.
- `description` — The description must contain only the type of document title (without numbers, dates, or identifiers, 1–2 sentences, **keep in Russian**).

# RULES:
- The document will be in Russian.
- **Crucial Rule:** If the document lists multiple products (e.g., in a numbered list), you MUST concatenate all "hs_code" values into a single string, separated by "; ". Similarly, concatenate all corresponding "description" values into a single string, separated by "; ".
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols and repeated whitespace.
- If a field cannot be found, set it to null.
- Output strict JSON only, with no text before or after.
"""

TRACKED_OTHER_INFORMATION_FIELDS = (
    "document_number",
    "document_date",
    "hs_code",
    "description",
)


class OtherInformationHandler(ConfiguredObjectHandler):
    document_code = "10999"
    label = "Other Information"
    prompt = OTHER_INFO_PROMPT
    tracked_fields = TRACKED_OTHER_INFORMATION_FIELDS

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
