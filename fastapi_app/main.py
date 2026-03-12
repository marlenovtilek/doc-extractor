from typing import Any

from fastapi import FastAPI, HTTPException

from extractor.api_service import execute_extraction_request
from extractor.health import get_health_status
from extractor.schemas import ExtractionRequest, ExtractionResponse


app = FastAPI(
    title="doc-extractor",
    version="0.1.0",
    description="Stateless extraction API for OCR invoice parsing.",
)


@app.get("/api/health/")
def health() -> dict:
    return get_health_status()


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
