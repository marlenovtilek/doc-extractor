"""Top-level invoice extraction pipeline orchestration."""

import time

from .currency import build_currency_db_string, finalize_items, load_currency_db
from .metrics import RunMetrics, compute_field_fill_rates, timer
from .postprocess import (
    deduplicate_items,
    extract_structured_pipe_items,
    filter_ocr_anomalies,
    post_fill_from_header,
    spread_single_country_origin,
    validate_and_parse,
)
from .preprocess import clean_text, extract_header, parse_full_doc_metadata, parse_header_metadata
from .providers import MODEL_PROFILES, extract_with_langextract_optimized, resolve_model_id
from .runtime import get_runtime_settings


def _merge_call_usage(*usages: dict) -> dict:
    known_calls = [usage for usage in usages if usage]
    if not known_calls:
        return {}

    total: dict[str, int] = {}
    for usage in known_calls:
        for key, value in usage.items():
            if not isinstance(value, int):
                continue
            total[key] = total.get(key, 0) + value
    return total


def run_invoice_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """
    Full pipeline for document_code == '04021'.
    """
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()
    runtime = get_runtime_settings()

    currency_db = load_currency_db()
    currency_db_str = build_currency_db_string(currency_db)

    with timer() as t:
        context = clean_text(ocr_draft, currency_db_str)
    metrics.t_clean_s = t[0]

    primary_model = resolve_model_id(model_id)
    fallback_spec = runtime.llm_model_fallback
    fallback_model = MODEL_PROFILES.get(fallback_spec, fallback_spec)
    effective_model = primary_model

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {"error": "Empty OCR text", "metrics": metrics.to_dict(), "model_id": effective_model}

    header_context = extract_header(context)
    header_meta = parse_header_metadata(header_context)
    for key, value in parse_full_doc_metadata(context).items():
        if key not in header_meta:
            header_meta[key] = value
    structured_items = extract_structured_pipe_items(context)

    def _extract(mid: str) -> tuple[str, object, dict]:
        return extract_with_langextract_optimized(context, mid, header_context)

    with timer() as t:
        raw_output, annotated_doc, primary_usage = _extract(primary_model)
    metrics.t_primary_llm_s = t[0]
    if primary_usage:
        metrics.token_usage["primary"] = primary_usage

    with timer() as t:
        validation = validate_and_parse(raw_output)
    metrics.t_validate_s = t[0]
    metrics.primary_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.fallback_used = True
        effective_model = fallback_model
        with timer() as t:
            raw_output, annotated_doc, fallback_usage = _extract(fallback_model)
        metrics.t_fallback_llm_s = t[0]
        if fallback_usage:
            metrics.token_usage["fallback"] = fallback_usage

        with timer() as t:
            validation = validate_and_parse(raw_output)
            metrics.t_validate_s += t[0]
        metrics.fallback_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": validation.get("error", "Extraction failed after fallback"),
            "metrics": metrics.to_dict(),
            "model_id": effective_model,
        }

    with timer() as t:
        items = validation["data"]["items"]
        items = post_fill_from_header(items, header_meta, currency_db)
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
        items = spread_single_country_origin(items)
        final_items = finalize_items(items, currency_db)
        final_items = filter_ocr_anomalies(final_items)
        final_items = deduplicate_items(final_items)

        structured_final_items = []
        if structured_items:
            structured_final_items = post_fill_from_header(structured_items, header_meta, currency_db)
            structured_final_items = spread_single_country_origin(structured_final_items)
            structured_final_items = finalize_items(structured_final_items, currency_db)
            structured_final_items = filter_ocr_anomalies(structured_final_items)
            structured_final_items = deduplicate_items(structured_final_items)

        if structured_final_items and len(structured_final_items) >= max(len(final_items) + 5, 10):
            positioned_llm_items = [item for item in final_items if item.get("position") is not None]
            merged_items = deduplicate_items(positioned_llm_items + structured_final_items)
            final_items = merged_items if len(merged_items) >= len(structured_final_items) else structured_final_items
    metrics.t_finalize_s = t[0]

    metrics.items_extracted = len(final_items)
    metrics.field_fill_rates = compute_field_fill_rates(final_items)
    total_usage = _merge_call_usage(
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
