from typing import Any

from fastapi import FastAPI, HTTPException, Response, Security
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from extractor.api_service import execute_extraction_request
from extractor.documents.registry import list_document_definitions
from extractor.health import get_health_status
from extractor.providers import (
    get_display_model_alias,
    get_display_model_family,
    get_provider_statuses,
    list_model_families,
    list_model_profiles,
)
from extractor.runtime import get_runtime_settings
from extractor.schemas import ExtractionRequest, ExtractionResponse
from .web_ui import render_home_page


app = FastAPI(
    title="doc-extractor",
    version="0.1.0",
    description="Stateless extraction API for OCR document parsing.",
)
_bearer_scheme = HTTPBearer(auto_error=False)


def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    runtime = get_runtime_settings()
    expected_token = runtime.doc_extractor_api_token.strip()
    if not expected_token:
        return

    presented_token = credentials.credentials.strip() if credentials else ""
    if presented_token == expected_token:
        return

    raise HTTPException(status_code=401, detail="Invalid or missing API token.")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return render_home_page()


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


def _health_payload() -> dict:
    return get_health_status()


def _meta_payload() -> dict[str, Any]:
    runtime = get_runtime_settings()
    documents = list_document_definitions()
    return {
        "documents": documents,
        "models": list_model_profiles(),
        "model_families": list_model_families(),
        "providers": get_provider_statuses(),
        "defaults": {
            "document_code": documents[0]["document_code"],
            "model_family": get_display_model_family(runtime.llm_model_primary),
            "model": get_display_model_alias(runtime.llm_model_primary),
            "fallback_model": get_display_model_alias(runtime.llm_model_fallback),
        },
    }


def _extract_payload(payload: ExtractionRequest) -> dict[str, Any]:
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


@app.get("/api/health/")
def health(_: None = Security(require_api_token)) -> dict:
    return _health_payload()


@app.get("/api/meta/")
def meta(_: None = Security(require_api_token)) -> dict[str, Any]:
    return _meta_payload()


@app.post("/api/extract/", response_model=ExtractionResponse)
def extract_document(
    payload: ExtractionRequest,
    _: None = Security(require_api_token),
) -> dict[str, Any]:
    return _extract_payload(payload)


@app.get("/web/health/", include_in_schema=False)
def web_health() -> dict:
    return _health_payload()


@app.get("/web/meta/", include_in_schema=False)
def web_meta() -> dict[str, Any]:
    return _meta_payload()


@app.post("/web/extract/", response_model=ExtractionResponse, include_in_schema=False)
def web_extract_document(payload: ExtractionRequest) -> dict[str, Any]:
    return _extract_payload(payload)
