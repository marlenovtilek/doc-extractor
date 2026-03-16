# extractor/documents/simple_base.py
from __future__ import annotations

from typing import Any

from .base import DocumentFieldSchema, DocumentSchema
from .contract import (
    _BaseObjectHandler,
    _run_object_document_extraction,
    TRACKED_SIMPLE_DOCUMENT_FIELDS,
)

SIMPLE_DOCUMENT_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a document in English or Russian. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the document (if any)
- `document_date` — the date of the document (normalize to DD/MM/YYYY if possible)
- `description` — {desc_instruction}

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

class BaseSimpleDocumentHandler(_BaseObjectHandler):
    """Базовый класс для всех простых документов с 3 полями (Номер, Дату, Описание)"""
    
    desc_instruction: str = "A concise description summarizing the document (1–2 sentences, **keep in Russian**)"
    
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        prompt = SIMPLE_DOCUMENT_PROMPT.format(desc_instruction=self.desc_instruction)
        output = _run_object_document_extraction(
            ocr_draft,
            model_id=model,
            prompt=prompt,
            examples=[],  # Для простых документов zero-shot отлично работает
            tracked_fields=TRACKED_SIMPLE_DOCUMENT_FIELDS,
            empty_error=f"No {self.label} fields extracted",
            label=self.label,
        )
        return self._wrap_object_output(output)