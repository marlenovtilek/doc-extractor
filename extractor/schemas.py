from typing import Any

from pydantic import BaseModel, Field


class ExtractionRequest(BaseModel):
    document_code: str = Field(..., examples=["04021"])
    ocr_draft: str
    model: str | None = None


class ExtractionResponse(BaseModel):
    status: str
    document_code: str
    result_type: str
    document_schema: dict[str, Any]
    data: dict[str, Any]
    model_id: str
    items: list[dict[str, Any]]
    count: int
    metrics: dict[str, Any]
    error: str
