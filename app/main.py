from typing import Any

from fastapi import FastAPI, HTTPException, Response, Security
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from extractor.config.runtime import get_runtime_settings
from extractor.contracts.schemas import ExtractionRequest, ExtractionResponse
from extractor.documents.registry import list_document_definitions
from extractor.integrations.providers import (
    get_display_model_alias,
    get_display_model_family,
    get_provider_statuses,
    list_model_families,
    list_model_profiles,
)
from extractor.services.extraction import execute_extraction_request
from extractor.services.health import get_health_status
from extractor.services.jobs import (
    cancel_web_extraction_job,
    get_web_extraction_job,
    submit_web_extraction_job,
)
from .web_ui import render_home_page


app = FastAPI(
    title="doc-extractor",
    version="0.1.0",
    description="Stateless extraction API for OCR document parsing.",
)
_bearer_scheme = HTTPBearer(auto_error=False)
_API_HIDDEN_ITEM_FIELDS = frozenset(
    {
        "parsing_confidence",
        "review_required",
        "review_priority",
        "review_reason_count",
        "review_notes",
        "part_no",
        "position",
    }
)


async def require_api_token(
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
async def home() -> str:
    return render_home_page()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
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


def _filter_public_api_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    return {
        key: value
        for key, value in item.items()
        if key not in _API_HIDDEN_ITEM_FIELDS
    }


def _filter_public_api_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    filtered = dict(schema)
    item_fields = filtered.get("item_fields")
    if isinstance(item_fields, list):
        filtered["item_fields"] = [
            field
            for field in item_fields
            if not (
                isinstance(field, dict)
                and field.get("name") in _API_HIDDEN_ITEM_FIELDS
            )
        ]
    return filtered


def _filter_public_api_response(response: dict[str, Any]) -> dict[str, Any]:
    filtered = dict(response)
    filtered["document_schema"] = _filter_public_api_schema(filtered.get("document_schema"))

    data = filtered.get("data")
    if isinstance(data, dict):
        filtered_data = dict(data)
        items = filtered_data.get("items", [])
        if isinstance(items, list):
            filtered_items = [_filter_public_api_item(item) for item in items]
            filtered_data["items"] = filtered_items
            filtered["items"] = filtered_items
            filtered["count"] = filtered_data.get("count", len(filtered_items))
        filtered["data"] = filtered_data
    return filtered


def _extract_payload(payload: ExtractionRequest, *, public_api: bool = False) -> dict[str, Any]:
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

    if public_api:
        return _filter_public_api_response(response)
    return response


@app.get("/api/health/")
async def health(_: None = Security(require_api_token)) -> dict:
    return _health_payload()


@app.get("/api/meta/")
async def meta(_: None = Security(require_api_token)) -> dict[str, Any]:
    return _meta_payload()


@app.post("/api/extract/", response_model=ExtractionResponse)
async def extract_document(
    payload: ExtractionRequest,
    _: None = Security(require_api_token),
) -> dict[str, Any]:
    return _extract_payload(payload, public_api=True)


@app.get("/web/health/", include_in_schema=False)
async def web_health() -> dict:
    return _health_payload()


@app.get("/web/meta/", include_in_schema=False)
async def web_meta() -> dict[str, Any]:
    return _meta_payload()


@app.post("/web/extract/", response_model=ExtractionResponse, include_in_schema=False)
async def web_extract_document(payload: ExtractionRequest) -> dict[str, Any]:
    return _extract_payload(payload, public_api=False)


@app.post("/web/jobs/", include_in_schema=False)
async def web_create_job(payload: ExtractionRequest) -> dict[str, Any]:
    try:
        return submit_web_extraction_job(
            document_code=payload.document_code,
            ocr_draft=payload.ocr_draft,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/web/jobs/{job_id}/", include_in_schema=False)
async def web_get_job(job_id: str) -> dict[str, Any]:
    try:
        return get_web_extraction_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc


@app.post("/web/jobs/{job_id}/cancel/", include_in_schema=False)
async def web_cancel_job(job_id: str) -> dict[str, Any]:
    try:
        return cancel_web_extraction_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc
