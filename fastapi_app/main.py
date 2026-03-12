from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from extractor.api_service import execute_extraction_request
from extractor.health import check_database, check_llm_api


class ExtractionRequest(BaseModel):
    document_code: str = Field(..., examples=["04021"])
    ocr_draft: str
    model: str | None = None


class ExtractionResponse(BaseModel):
    status: str
    document_code: str
    model_id: str
    items: list[dict[str, Any]]
    count: int
    metrics: dict[str, Any]
    error: str


app = FastAPI(
    title="doc-extractor",
    version="0.1.0",
    description="Stateless extraction API for OCR invoice parsing.",
)


@app.get("/api/health/")
def health() -> dict[str, Any]:
    db = check_database()
    llm = check_llm_api()
    all_ok = llm["status"] == "ok"
    return {
        "status": "ok" if all_ok else "degraded",
        "database": db,
        "llm_api": llm,
    }


@app.post("/api/extract/", response_model=ExtractionResponse)
def extract_invoice(payload: ExtractionRequest) -> dict[str, Any]:
    try:
        response = execute_extraction_request(
            document_code=payload.document_code,
            ocr_draft=payload.ocr_draft,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if response["status"] == "failed":
        raise HTTPException(status_code=500, detail=response["error"])

    return response
