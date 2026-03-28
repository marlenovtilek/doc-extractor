import re
from typing import Any

from ..config.runtime import get_runtime_settings
from ..context.execution import ensure_not_cancelled, report_progress
from ..documents.registry import get_document_definition
from ..integrations.providers import ensure_model_spec_ready


def _count_pipe_like_rows(text: str) -> int:
    return sum(1 for line in (text or "").splitlines() if line.count("|") >= 4)


def _count_html_table_tags(text: str) -> int:
    return len(re.findall(r"</?(td|th|tr)\b", text or "", flags=re.IGNORECASE))


def _pick_first_ready_model(candidates: list[str]) -> tuple[str, object]:
    last_error: ValueError | None = None
    seen: set[str] = set()

    for spec in candidates:
        normalized = (spec or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            target = ensure_model_spec_ready(normalized)
            return normalized, target
        except ValueError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("No configured model candidate available for this request.")


def _resolve_requested_or_auto_model(
    *,
    requested_model: str | None,
    result_type: str,
    ocr_draft: str,
) -> tuple[str, dict[str, Any]]:
    runtime = get_runtime_settings()

    if requested_model:
        requested = requested_model.strip()
        target = ensure_model_spec_ready(requested)
        return requested, {
            "mode": "manual",
            "requested_model": requested,
            "selected_model": requested,
            "provider": target.provider,
            "model_id": target.model_id,
            "reason": "user_selected_model",
        }

    if not runtime.model_auto_route:
        selected, target = _pick_first_ready_model(
            [runtime.llm_model_primary, runtime.llm_model_fallback]
        )
        return selected, {
            "mode": "default",
            "requested_model": None,
            "selected_model": selected,
            "provider": target.provider,
            "model_id": target.model_id,
            "reason": "auto_route_disabled",
        }

    char_count = len(ocr_draft or "")
    pipe_like_rows = _count_pipe_like_rows(ocr_draft)
    html_table_tags = _count_html_table_tags(ocr_draft)
    looks_large_tabular = (
        char_count >= runtime.auto_route_char_threshold
        or pipe_like_rows >= runtime.auto_route_pipe_row_threshold
        or html_table_tags >= runtime.auto_route_pipe_row_threshold
    )

    if result_type == "table" and looks_large_tabular:
        reason = "large_or_tabular_table_document"
        candidates = [
            runtime.model_auto_route_large_table,
            runtime.llm_model_primary,
            runtime.llm_model_fallback,
            "cerebras",
            runtime.model_auto_route_small_doc,
        ]
    elif result_type == "table":
        reason = "small_table_document"
        candidates = [
            runtime.model_auto_route_small_doc,
            runtime.llm_model_primary,
            runtime.llm_model_fallback,
            runtime.model_auto_route_large_table,
        ]
    else:
        reason = "object_document"
        candidates = [
            runtime.model_auto_route_object_default,
            runtime.llm_model_fallback,
            runtime.llm_model_primary,
            runtime.model_auto_route_small_doc,
        ]

    selected, target = _pick_first_ready_model(candidates)
    return selected, {
        "mode": "auto",
        "requested_model": None,
        "selected_model": selected,
        "provider": target.provider,
        "model_id": target.model_id,
        "reason": reason,
        "signals": {
            "result_type": result_type,
            "char_count": char_count,
            "pipe_like_rows": pipe_like_rows,
            "html_table_tags": html_table_tags,
            "char_threshold": runtime.auto_route_char_threshold,
            "pipe_row_threshold": runtime.auto_route_pipe_row_threshold,
        },
    }


def _build_response(
    *,
    status: str,
    document_code: str,
    result_type: str,
    document_schema: dict[str, Any],
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
        "document_schema": document_schema,
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
    report_progress("routing", "Selecting the document handler.")
    ensure_not_cancelled()
    definition = get_document_definition(document_code)
    handler = definition.handler
    selected_model, selection_info = _resolve_requested_or_auto_model(
        requested_model=model,
        result_type=definition.schema.result_type,
        ocr_draft=ocr_draft,
    )
    report_progress(
        "extracting",
        f"Running {definition.label} with {selection_info['selected_model']}.",
    )
    ensure_not_cancelled()
    output = handler.extract(ocr_draft=ocr_draft, model=selected_model)
    ensure_not_cancelled()

    metrics = dict(output.get("metrics", {}))
    metrics["model_selection"] = selection_info
    model_id_used = output.get("model_id", "")
    result_type = output.get("result_type", getattr(handler, "result_type", "object"))
    document_schema = definition.schema.to_dict()
    data = output.get("data", {})
    if "error" in output:
        return _build_response(
            status="failed",
            document_code=document_code,
            result_type=result_type,
            document_schema=document_schema,
            data=data,
            model_id=model_id_used,
            metrics=metrics,
            error=output["error"],
        )

    return _build_response(
        status="success",
        document_code=document_code,
        result_type=result_type,
        document_schema=document_schema,
        data=data,
        model_id=model_id_used,
        metrics=metrics,
        error="",
    )
