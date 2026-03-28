from __future__ import annotations

from typing import Any, Callable

from ...integrations.providers import ModelTarget
from ...observability.metrics import merge_token_usage
from .invoice_postprocess import (
    deduplicate_items,
    prepare_invoice_items_for_merge,
    normalize_invoice_items,
    sort_items_by_position,
)


def _build_invoice_subset_context(context: str, lines: list[str]) -> str:
    prefix, sep, _ = context.partition("=== INVOICE CONTENT ===\n")
    if not sep:
        return context
    return prefix + sep + "\n".join(lines)


def run_line_level_llm_assist(
    context: str,
    header_context: str,
    header_meta: dict,
    currency_db: list[dict],
    candidate_lines: list[str],
    primary_model: ModelTarget,
    fallback_model: ModelTarget,
    *,
    extract_with_timing: Callable[[str, str, ModelTarget], dict[str, Any]],
) -> dict[str, object]:
    if not candidate_lines:
        return {
            "items": [],
            "raw_output": "[]",
            "annotated_doc": None,
            "usage": {},
            "fallback_used": False,
            "model_id": None,
            "valid": False,
        }

    mini_context = _build_invoice_subset_context(context, candidate_lines)
    result = extract_with_timing(mini_context, header_context, primary_model)
    validation = result["validation"]
    effective_model = primary_model.model_id
    usage = result["usage"] or {}
    fallback_used = False

    if not validation["is_valid"]:
        fallback_used = True
        result = extract_with_timing(mini_context, header_context, fallback_model)
        validation = result["validation"]
        effective_model = fallback_model.model_id
        usage = merge_token_usage(usage, result["usage"] or {})

    if not validation["is_valid"]:
        return {
            "items": [],
            "raw_output": result["raw_output"],
            "annotated_doc": result["annotated_doc"],
            "usage": usage,
            "fallback_used": fallback_used,
            "model_id": effective_model,
            "valid": False,
        }

    repaired_items = prepare_invoice_items_for_merge(validation["data"]["items"], header_meta, currency_db)
    return {
        "items": repaired_items,
        "raw_output": result["raw_output"],
        "annotated_doc": result["annotated_doc"],
        "usage": usage,
        "fallback_used": fallback_used,
        "model_id": effective_model,
        "valid": True,
    }


def recover_with_structured_items(
    llm_items: list[dict],
    structured_items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
) -> list[dict]:
    if not structured_items:
        return llm_items

    structured_final_items = normalize_invoice_items(structured_items, header_meta, currency_db)
    if not structured_final_items:
        return llm_items

    if len(structured_final_items) < max(len(llm_items) + 5, 10):
        return llm_items

    positioned_llm_items = [item for item in llm_items if item.get("position") is not None]
    merged_items = deduplicate_items(positioned_llm_items + structured_final_items)
    if len(merged_items) >= len(structured_final_items):
        return sort_items_by_position(merged_items)
    return sort_items_by_position(structured_final_items)
