from __future__ import annotations

import time
from typing import Callable

from ...integrations.providers import ModelTarget
from ...observability.metrics import RunMetrics, compute_field_fill_rates, merge_token_usage, timer


def _prepare_structured_parser_result(
    *,
    context: str,
    currency_db: list[dict],
    build_header_metadata: Callable[[str], tuple[str, dict]],
    extract_structured_pipe_items: Callable[[str], list[dict]],
    normalize_invoice_items: Callable[..., list[dict]],
    assess_structured_parser: Callable[[str, list[dict]], dict],
) -> tuple[str, dict, list[dict], dict, bool, list[dict]]:
    header_context, header_meta = build_header_metadata(context)
    structured_items = extract_structured_pipe_items(context)

    structured_prepared_items = normalize_invoice_items(
        structured_items,
        header_meta,
        currency_db,
        preserve_exact_line_duplicates=True,
        annotate_review=False,
        strip_internal_fields=False,
        sort_output=False,
    )
    parser_assessment = assess_structured_parser(context, structured_prepared_items)
    preserve_exact_line_duplicates = parser_assessment["duplicate_inflation_ratio"] < 1.15

    structured_final_items = normalize_invoice_items(
        structured_items,
        header_meta,
        currency_db,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )
    return (
        header_context,
        header_meta,
        structured_items,
        parser_assessment,
        preserve_exact_line_duplicates,
        structured_final_items,
    )


def _try_line_level_assist(
    *,
    context: str,
    header_context: str,
    header_meta: dict,
    currency_db: list[dict],
    structured_items: list[dict],
    structured_final_items: list[dict],
    preserve_exact_line_duplicates: bool,
    primary_model: ModelTarget,
    fallback_model: ModelTarget,
    metrics: RunMetrics,
    extract_with_timing: Callable[[str, str, ModelTarget], dict],
    collect_line_level_repair_candidates: Callable[[str, list[dict]], list[str]],
    run_line_level_llm_assist: Callable[..., dict],
    merge_normalized_invoice_items: Callable[..., list[dict]],
    report_progress: Callable[[str, str], None],
    ensure_not_cancelled: Callable[[], None],
) -> tuple[list[dict], dict]:
    assist_candidates = collect_line_level_repair_candidates(context, structured_items)
    assist_details = {
        "candidate_lines": len(assist_candidates),
        "repaired_items": 0,
        "used": False,
        "fallback_used": False,
        "model_id": None,
    }
    if not assist_candidates:
        return structured_final_items, assist_details

    report_progress(
        "llm_assist",
        f"Repairing {len(assist_candidates)} unresolved invoice rows with selective LLM assist.",
    )
    ensure_not_cancelled()
    with timer() as t_assist:
        assist_result = run_line_level_llm_assist(
            context,
            header_context,
            header_meta,
            currency_db,
            assist_candidates,
            primary_model,
            fallback_model,
            extract_with_timing=extract_with_timing,
        )
    metrics.t_primary_llm_s = t_assist[0]
    if assist_result["usage"]:
        metrics.token_usage["assist"] = assist_result["usage"]
        metrics.token_usage["total"] = assist_result["usage"]

    if not (assist_result["valid"] and assist_result["items"]):
        return structured_final_items, assist_details

    merged_items = structured_final_items + assist_result["items"]
    merged_normalized_items = merge_normalized_invoice_items(
        merged_items,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )
    if len(merged_normalized_items) >= len(structured_final_items):
        assist_details.update(
            {
                "repaired_items": len(assist_result["items"]),
                "used": True,
                "fallback_used": bool(assist_result["fallback_used"]),
                "model_id": assist_result["model_id"],
            }
        )
        return merged_normalized_items, assist_details

    assist_details.update(
        {
            "discarded": True,
            "discard_reason": "reduced_parser_count",
            "fallback_used": bool(assist_result["fallback_used"]),
            "model_id": assist_result["model_id"],
        }
    )
    return structured_final_items, assist_details


def _build_parser_first_response(
    *,
    items: list[dict],
    metrics: RunMetrics,
    t_wall_start: float,
) -> dict:
    metrics.primary_valid = True
    metrics.items_extracted = len(items)
    metrics.field_fill_rates = compute_field_fill_rates(items)
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)
    return {
        "result": {"items": items, "count": len(items)},
        "metrics": metrics.to_dict(),
        "annotated_doc": None,
        "model_id": "structured-parser",
        "raw_llm_output": "[]",
    }


def _run_llm_validation_path(
    *,
    context: str,
    header_context: str,
    primary_model: ModelTarget,
    fallback_model: ModelTarget,
    metrics: RunMetrics,
    extract_with_timing: Callable[[str, str, ModelTarget], dict],
    report_progress: Callable[[str, str], None],
    ensure_not_cancelled: Callable[[], None],
) -> tuple[dict | None, str, object | None, dict | None, str]:
    effective_model = primary_model.model_id

    report_progress(
        "llm_primary",
        f"Running primary model {primary_model.provider}::{primary_model.model_id}.",
    )
    ensure_not_cancelled()
    primary_result = extract_with_timing(context, header_context, primary_model)
    raw_output = primary_result["raw_output"]
    annotated_doc = primary_result["annotated_doc"]
    validation = primary_result["validation"]
    metrics.t_primary_llm_s = primary_result["llm_seconds"]
    metrics.t_validate_s = primary_result["validate_seconds"]
    if primary_result["usage"]:
        metrics.token_usage["primary"] = primary_result["usage"]
    metrics.primary_valid = bool(validation["is_valid"])

    if validation["is_valid"]:
        return None, raw_output, annotated_doc, validation, effective_model

    metrics.fallback_used = True
    effective_model = fallback_model.model_id
    report_progress(
        "llm_fallback",
        f"Retrying with fallback model {fallback_model.provider}::{fallback_model.model_id}.",
    )
    ensure_not_cancelled()
    fallback_result = extract_with_timing(context, header_context, fallback_model)
    raw_output = fallback_result["raw_output"]
    annotated_doc = fallback_result["annotated_doc"]
    validation = fallback_result["validation"]
    metrics.t_fallback_llm_s = fallback_result["llm_seconds"]
    metrics.t_validate_s += fallback_result["validate_seconds"]
    if fallback_result["usage"]:
        metrics.token_usage["fallback"] = fallback_result["usage"]
    metrics.fallback_valid = bool(validation["is_valid"])

    if validation["is_valid"]:
        return None, raw_output, annotated_doc, validation, effective_model

    return (
        {
            "error": validation.get("error", "Extraction failed after fallback"),
            "metrics": metrics.to_dict(),
            "model_id": effective_model,
        },
        raw_output,
        annotated_doc,
        validation,
        effective_model,
    )


def _finalize_llm_items(
    *,
    validation: dict,
    header_meta: dict,
    currency_db: list[dict],
    structured_items: list[dict],
    normalize_invoice_items: Callable[..., list[dict]],
    recover_with_structured_items: Callable[..., list[dict]],
) -> list[dict]:
    final_items = normalize_invoice_items(validation["data"]["items"], header_meta, currency_db)
    return recover_with_structured_items(
        final_items,
        structured_items,
        header_meta,
        currency_db,
    )


def execute_invoice_extraction(
    *,
    ocr_draft: str,
    primary_model: ModelTarget,
    fallback_model: ModelTarget,
    metrics: RunMetrics,
    extract_with_timing: Callable[[str, str, ModelTarget], dict],
    load_currency_db: Callable[[], list[dict]],
    build_currency_db_string: Callable[[list[dict]], str],
    clean_text: Callable[[str, str], str],
    build_header_metadata: Callable[[str], tuple[str, dict]],
    extract_structured_pipe_items: Callable[[str], list[dict]],
    normalize_invoice_items: Callable[..., list[dict]],
    merge_normalized_invoice_items: Callable[..., list[dict]],
    assess_structured_parser: Callable[[str, list[dict]], dict],
    collect_line_level_repair_candidates: Callable[[str, list[dict]], list[str]],
    run_line_level_llm_assist: Callable[..., dict],
    recover_with_structured_items: Callable[..., list[dict]],
    report_progress: Callable[[str, str], None],
    ensure_not_cancelled: Callable[[], None],
) -> dict:
    t_wall_start = time.perf_counter()
    currency_db = load_currency_db()
    currency_db_str = build_currency_db_string(currency_db)

    report_progress("cleaning", "Preparing OCR text for invoice extraction.")
    ensure_not_cancelled()
    with timer() as t:
        context = clean_text(ocr_draft, currency_db_str)
    metrics.t_clean_s = t[0]

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": "Empty OCR text",
            "metrics": metrics.to_dict(),
            "model_id": primary_model.model_id,
        }

    report_progress("parsing", "Building invoice header metadata and structured rows.")
    ensure_not_cancelled()
    (
        header_context,
        header_meta,
        structured_items,
        parser_assessment,
        preserve_exact_line_duplicates,
        structured_final_items,
    ) = _prepare_structured_parser_result(
        context=context,
        currency_db=currency_db,
        build_header_metadata=build_header_metadata,
        extract_structured_pipe_items=extract_structured_pipe_items,
        normalize_invoice_items=normalize_invoice_items,
        assess_structured_parser=assess_structured_parser,
    )
    metrics.execution_path = {
        "mode": "parser_first" if parser_assessment["use_parser_first"] else "llm_first",
        "structured_parser": parser_assessment,
    }

    if parser_assessment["use_parser_first"]:
        structured_final_items, assist_details = _try_line_level_assist(
            context=context,
            header_context=header_context,
            header_meta=header_meta,
            currency_db=currency_db,
            structured_items=structured_items,
            structured_final_items=structured_final_items,
            preserve_exact_line_duplicates=preserve_exact_line_duplicates,
            primary_model=primary_model,
            fallback_model=fallback_model,
            metrics=metrics,
            extract_with_timing=extract_with_timing,
            collect_line_level_repair_candidates=collect_line_level_repair_candidates,
            run_line_level_llm_assist=run_line_level_llm_assist,
            merge_normalized_invoice_items=merge_normalized_invoice_items,
            report_progress=report_progress,
            ensure_not_cancelled=ensure_not_cancelled,
        )
        if assist_details["candidate_lines"]:
            metrics.execution_path["assist"] = assist_details
        return _build_parser_first_response(
            items=structured_final_items,
            metrics=metrics,
            t_wall_start=t_wall_start,
        )

    error_result, raw_output, annotated_doc, validation, effective_model = _run_llm_validation_path(
        context=context,
        header_context=header_context,
        primary_model=primary_model,
        fallback_model=fallback_model,
        metrics=metrics,
        extract_with_timing=extract_with_timing,
        report_progress=report_progress,
        ensure_not_cancelled=ensure_not_cancelled,
    )
    if error_result is not None:
        error_result["metrics"]["t_total_s"] = time.perf_counter() - t_wall_start
        return error_result

    report_progress("finalizing", "Normalizing and merging extracted invoice rows.")
    ensure_not_cancelled()
    with timer() as t:
        final_items = _finalize_llm_items(
            validation=validation,
            header_meta=header_meta,
            currency_db=currency_db,
            structured_items=structured_items,
            normalize_invoice_items=normalize_invoice_items,
            recover_with_structured_items=recover_with_structured_items,
        )
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
