from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DocumentHandler(ABC):
    """Document-specific extraction strategy."""

    document_code: str
    result_type: str

    @abstractmethod
    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        """Run extraction for a specific document type."""
