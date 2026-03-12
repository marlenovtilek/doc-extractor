from typing import Any

from .documents.registry import get_document_handler


def _build_response(
    *,
    status: str,
    document_code: str,
    result_type: str,
    data: dict[str, Any],
    model_id: str,
    metrics: dict,
    error: str,
) -> dict:
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    count = data.get("count", len(items))
    return {
        "status": status,
        "document_code": document_code,
        "result_type": result_type,
        "data": data,
        "model_id": model_id,
        "items": items,
        "count": count,
        "metrics": metrics,
        "error": error,
    }


def execute_extraction_request(
    *,
    document_code: str,
    ocr_draft: str,
    model: str | None = None,
) -> dict:
    handler = get_document_handler(document_code)
    output = handler.extract(ocr_draft=ocr_draft, model=model)

    metrics = output.get("metrics", {})
    model_id_used = output.get("model_id", "")
    result_type = output.get("result_type", getattr(handler, "result_type", "object"))
    data = output.get("data", {})
    if "error" in output:
        return _build_response(
            status="failed",
            document_code=document_code,
            result_type=result_type,
            data=data,
            model_id=model_id_used,
            metrics=metrics,
            error=output["error"],
        )

    return _build_response(
        status="success",
        document_code=document_code,
        result_type=result_type,
        data=data,
        model_id=model_id_used,
        metrics=metrics,
        error="",
    )
