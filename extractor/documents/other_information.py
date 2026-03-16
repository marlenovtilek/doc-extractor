from __future__ import annotations

from typing import Any
from .base import DocumentFieldSchema, DocumentSchema
from .contract import _BaseObjectHandler, _run_object_document_extraction

# Полный промпт из твоего Dify для узла 1766571705613
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

class OtherInformationHandler(_BaseObjectHandler):
    document_code = "10999"
    label = "Other Information"
    
    # Схема с 4 полями
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

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = _run_object_document_extraction(
            ocr_draft,
            model_id=model,
            prompt=OTHER_INFO_PROMPT,
            examples=[],  # Zero-shot для этого промпта достаточно
            tracked_fields=("document_number", "document_date", "hs_code", "description"),
            empty_error=f"No {self.label} fields extracted",
            label=self.label,
        )
        return self._wrap_object_output(output)