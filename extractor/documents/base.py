from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentFieldSchema:
    """Schema for a single extracted field."""

    name: str
    label: str
    kind: str = "string"
    required: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class DocumentSchema:
    """Document-specific extraction contract."""

    result_type: str
    fields: tuple[DocumentFieldSchema, ...] = field(default_factory=tuple)
    item_fields: tuple[DocumentFieldSchema, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "result_type": self.result_type,
            "fields": [item.to_dict() for item in self.fields],
            "item_fields": [item.to_dict() for item in self.item_fields],
        }


@dataclass(frozen=True)
class DocumentDefinition:
    """Registered document type with its handler and schema."""

    document_code: str
    label: str
    handler: "DocumentHandler"
    schema: DocumentSchema

    def to_dict(self) -> dict[str, object]:
        return {
            "document_code": self.document_code,
            "label": self.label,
            "result_type": self.schema.result_type,
            "schema": self.schema.to_dict(),
        }


class DocumentHandler(ABC):
    """Document-specific extraction strategy."""

    document_code: str
    label: str
    schema: DocumentSchema

    @property
    def result_type(self) -> str:
        return self.schema.result_type

    @abstractmethod
    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        """Run extraction for a specific document type."""
