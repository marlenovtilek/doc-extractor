from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Response, Security, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from extractor.runtime import get_runtime_settings
from extractor.schemas import ExtractionRequest, ExtractionResponse
from extractor.registry import list_document_definitions
from extractor.providers import (
    get_provider_statuses,
    list_model_families,
    resolve_model_target
)
from extractor.extraction import execute_extraction_request
from extractor.health import get_health_status
from extractor.jobs import (
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

# Поля, которые мы скрываем только в публичном API, но оставляем в Web UI
_API_HIDDEN_ITEM_FIELDS = frozenset(
    {
        "parsing_confidence",
        "review_required",
        "review_priority",
        "review_reason_count",
        "review_notes",
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
async def home() -> HTMLResponse:
    # Вызывает нашу новую динамическую страницу
    return render_home_page()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


def _health_payload() -> dict:
    return get_health_status()


def _meta_payload() -> dict[str, Any]:
    """Формирует мета-данные для фронтенда на основе новых динамических функций."""
    runtime = get_runtime_settings()
    documents = list_document_definitions()
    families = list_model_families()
    
    return {
        "documents": documents,
        "model_families": families,
        "providers": get_provider_statuses(),
        "defaults": {
            "document_code": documents[0]["document_code"] if documents else "04021",
            "model": runtime.llm_model_primary,
            "fallback_model": runtime.llm_model_fallback,
        },
    }


def _filter_public_api_response(response: dict[str, Any]) -> dict[str, Any]:
    """Упрощает ответ для публичного API (удаляет метаданные чанкинга и т.д.)."""
    data = dict(response.get("data", {}))
    items = data.get("items", [])
    
    # Фильтруем скрытые поля в товарах
    if isinstance(items, list):
        filtered_items = []
        for item in items:
            filtered_items.append({
                k: v for k, v in item.items() if k not in _API_HIDDEN_ITEM_FIELDS
            })
        data["items"] = filtered_items

    filtered_response = {
        "status": response.get("status", "unknown"),
        "document_code": response.get("document_code", ""),
        "duration": response.get("duration", 0.0),
        "error": response.get("error", ""),
        "data": data,
    }
    for key in ("result_type", "model_id", "metrics"):
        if key in response:
            filtered_response[key] = response[key]
    return filtered_response


def _classify_error_status(error_detail: str) -> int:
    lowered = error_detail.lower()
    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return 429
    if "timed out" in lowered or "timeout" in lowered:
        return 504
    if "network error" in lowered:
        return 503
    if "request failed for model" in lowered:
        return 502
    if (
        "unsupported" in lowered
        or "empty ocr text" in lowered
        or "empty model id" in lowered
        or "no models configured" in lowered
    ):
        return 400
    if (
        "failed to parse structured response" in lowered
        or "no invoice items extracted" in lowered
        or "no fields extracted" in lowered
        or "extraction failed for both primary and fallback models" in lowered
    ):
        return 422
    return 500


def _extract_payload(payload: ExtractionRequest, *, public_api: bool = False) -> dict[str, Any]:
    try:
        response = execute_extraction_request(
            document_code=payload.document_code,
            ocr_draft=payload.ocr_draft,
            model=payload.model,
            source_file_path=payload.source_file_path,
        )
        
        if response.get("status") == "failed":
            # Пробрасываем ошибку из хэндлера
            error_detail = response.get("error", "Extraction failed")
            raise HTTPException(status_code=_classify_error_status(error_detail), detail=error_detail)

        if public_api:
            return _filter_public_api_response(response)
        
        return response

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        # Логируем критические ошибки сервера
        import logging
        logging.error(f"Critical error during extraction: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error during extraction")


def _store_uploaded_source_file(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix
    target_dir = Path("/tmp/doc-extractor-uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex}{suffix}"
    with target_path.open("wb") as target_file:
        shutil.copyfileobj(upload.file, target_file)
    return target_path


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
    # Web-версия получает полный ответ (без фильтрации полей)
    return _extract_payload(payload, public_api=False)


@app.post("/web/extract/upload/", response_model=ExtractionResponse, include_in_schema=False)
async def web_extract_document_upload(
    document_code: str = Form(...),
    ocr_draft: str = Form(""),
    model: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    normalized_model = model.strip() if isinstance(model, str) else model
    source_file_path: str | None = None
    stored_path: Path | None = None

    try:
        target = resolve_model_target(normalized_model)

        if target.provider == "vlm" and file is None:
            raise HTTPException(status_code=400, detail="VLM extraction requires an uploaded PDF or image file.")
        if target.provider != "vlm" and not str(ocr_draft or "").strip():
            raise HTTPException(status_code=400, detail="OCR text is required for non-VLM models.")

        if file is not None:
            stored_path = _store_uploaded_source_file(file)
            source_file_path = str(stored_path)

        payload = ExtractionRequest(
            document_code=document_code,
            ocr_draft=ocr_draft,
            model=normalized_model or None,
            source_file_path=source_file_path,
        )
        return _extract_payload(payload, public_api=False)
    finally:
        if file is not None:
            await file.close()
        if stored_path is not None:
            stored_path.unlink(missing_ok=True)


# --- JOB MANAGEMENT (Оставляем без изменений, они используют общие сервисы) ---

@app.post("/web/jobs/", include_in_schema=False)
async def web_create_job(payload: ExtractionRequest) -> dict[str, Any]:
    try:
        return submit_web_extraction_job(
            document_code=payload.document_code,
            ocr_draft=payload.ocr_draft,
            model=payload.model,
            source_file_path=payload.source_file_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/web/jobs/{job_id}/", include_in_schema=False)
async def web_get_job(job_id: str) -> dict[str, Any]:
    try:
        return get_web_extraction_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.")


@app.post("/web/jobs/{job_id}/cancel/", include_in_schema=False)
async def web_cancel_job(job_id: str) -> dict[str, Any]:
    try:
        return cancel_web_extraction_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.")
