"""Top-level invoice extraction pipeline orchestration."""

import time

from .currency import build_currency_db_string, finalize_items, load_currency_db
from .metrics import RunMetrics, compute_field_fill_rates, merge_token_usage, timer
from .postprocess import (
    deduplicate_items,
    extract_structured_pipe_items,
    filter_ocr_anomalies,
    post_fill_from_header,
    sort_items_by_position,
    spread_single_country_origin,
    validate_and_parse,
)
from .preprocess import clean_text, extract_header, parse_full_doc_metadata, parse_header_metadata
from .providers import ModelTarget, extract_with_langextract_optimized, resolve_model_target


def _resolve_models(model_id: str | None) -> tuple[ModelTarget, ModelTarget]:
    from .runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    return primary_model, fallback_model


def _build_header_metadata(context: str) -> tuple[str, dict]:
    header_context = extract_header(context)
    header_meta = parse_header_metadata(header_context)
    for key, value in parse_full_doc_metadata(context).items():
        if key not in header_meta:
            header_meta[key] = value
    return header_context, header_meta


def _extract_with_timing(context: str, header_context: str, model: ModelTarget) -> dict:
    with timer() as t_llm:
        raw_output, annotated_doc, usage = extract_with_langextract_optimized(context, model, header_context)
    with timer() as t_validate:
        validation = validate_and_parse(raw_output)
    return {
        "raw_output": raw_output,
        "annotated_doc": annotated_doc,
        "usage": usage,
        "validation": validation,
        "llm_seconds": t_llm[0],
        "validate_seconds": t_validate[0],
    }


def _fill_derived_item_fields(items: list[dict]) -> list[dict]:
    for item in items:
        cost = item.get("cost")
        is_empty_cost = cost is None or str(cost).strip().lower() in ("", "null", "none", "0")
        if is_empty_cost:
            try:
                price = float(item.get("price") or 0)
                qty = float(item.get("quantity") or 1)
                item["cost"] = round(price / qty, 4) if qty else price
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        unit = item.get("unit")
        if unit is None or str(unit).strip().lower() in ("", "null", "none"):
            item["unit"] = "pcs"
    return items


def _normalize_items(items: list[dict], header_meta: dict, currency_db: list[dict]) -> list[dict]:
    normalized = post_fill_from_header(items, header_meta, currency_db)
    normalized = _fill_derived_item_fields(normalized)
    normalized = spread_single_country_origin(normalized)
    normalized = finalize_items(normalized, currency_db)
    normalized = filter_ocr_anomalies(normalized)
    return sort_items_by_position(deduplicate_items(normalized))


def _recover_with_structured_items(
    llm_items: list[dict],
    structured_items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
) -> list[dict]:
    if not structured_items:
        return llm_items

    structured_final_items = _normalize_items(structured_items, header_meta, currency_db)
    if not structured_final_items:
        return llm_items

    if len(structured_final_items) < max(len(llm_items) + 5, 10):
        return llm_items

    positioned_llm_items = [item for item in llm_items if item.get("position") is not None]
    merged_items = deduplicate_items(positioned_llm_items + structured_final_items)
    if len(merged_items) >= len(structured_final_items):
        return sort_items_by_position(merged_items)
    return sort_items_by_position(structured_final_items)


def run_invoice_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """
    Full pipeline for document_code == '04021'.
    """
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    currency_db = load_currency_db()
    currency_db_str = build_currency_db_string(currency_db)

    with timer() as t:
        context = clean_text(ocr_draft, currency_db_str)
    metrics.t_clean_s = t[0]
    primary_model, fallback_model = _resolve_models(model_id)
    effective_model = primary_model.model_id

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {"error": "Empty OCR text", "metrics": metrics.to_dict(), "model_id": effective_model}

    header_context, header_meta = _build_header_metadata(context)
    structured_items = extract_structured_pipe_items(context)
    primary_result = _extract_with_timing(context, header_context, primary_model)
    raw_output = primary_result["raw_output"]
    annotated_doc = primary_result["annotated_doc"]
    validation = primary_result["validation"]
    metrics.t_primary_llm_s = primary_result["llm_seconds"]
    metrics.t_validate_s = primary_result["validate_seconds"]
    if primary_result["usage"]:
        metrics.token_usage["primary"] = primary_result["usage"]
    metrics.primary_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.fallback_used = True
        effective_model = fallback_model.model_id
        fallback_result = _extract_with_timing(context, header_context, fallback_model)
        raw_output = fallback_result["raw_output"]
        annotated_doc = fallback_result["annotated_doc"]
        validation = fallback_result["validation"]
        metrics.t_fallback_llm_s = fallback_result["llm_seconds"]
        metrics.t_validate_s += fallback_result["validate_seconds"]
        if fallback_result["usage"]:
            metrics.token_usage["fallback"] = fallback_result["usage"]
        metrics.fallback_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": validation.get("error", "Extraction failed after fallback"),
            "metrics": metrics.to_dict(),
            "model_id": effective_model,
        }

    with timer() as t:
        final_items = _normalize_items(validation["data"]["items"], header_meta, currency_db)
        final_items = _recover_with_structured_items(final_items, structured_items, header_meta, currency_db)
    metrics.t_finalize_s = t[0]

    metrics.items_extracted = len(final_items)
    metrics.field_fill_rates = compute_field_fill_rates(final_items)
    total_usage = merge_token_usage(
        metrics.token_usage.get("primary", {}),
        metrics.token_usage.get("fallback", {}),
    )
    if total_usage:
        metrics.token_usage["total"] = total_usage
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"items": final_items, "count": len(final_items)},
        "metrics": metrics.to_dict(),
        "annotated_doc": annotated_doc,
        "model_id": effective_model,
        "raw_llm_output": raw_output,
    }
