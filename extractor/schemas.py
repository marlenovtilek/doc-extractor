from typing import Any

from pydantic import BaseModel, Field


class ExtractionRequest(BaseModel):
    document_code: str = Field(..., examples=["04021"])
    ocr_draft: str
    model: str | None = None
    source_file_path: str | None = None


class ExtractionResponse(BaseModel):
    """Simplified response for extraction API."""
    status: str
    document_code: str
    duration: float
    error: str
    data: dict[str, Any]
    result_type: str | None = None
    model_id: str | None = None
    metrics: dict[str, Any] | None = None
