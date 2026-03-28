from __future__ import annotations

from typing import Any

from ..base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from .invoice_assist import recover_with_structured_items, run_line_level_llm_assist
from .invoice_cleaner import clean_text, _extract_inline_blob_pipe_rows, _trim_item_line
from .invoice_header import build_header_metadata
from .invoice_llm import (
    EXAMPLES,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_GPT_OSS,
    _CEREBRAS_RESPONSE_FORMAT,
    _repair_json,
    validate_and_parse,
)
from .invoice_parser import (
    _build_structured_line_signature,
    _extract_hs_last_item,
    _extract_sparse_hs_item_without_country,
    extract_structured_pipe_items,
)
from .invoice_parser_assessment import (
    _assess_structured_parser,
    _collect_line_level_repair_candidates,
)
from .invoice_pipeline import execute_invoice_extraction
from .invoice_postprocess import (
    deduplicate_items,
    filter_ocr_anomalies,
    merge_normalized_invoice_items,
    normalize_invoice_items,
    post_fill_from_header,
    sort_items_by_position,
    spread_single_country_origin,
)
from ..regular.technical_document import (
    TechnicalDocumentHandler as _RegularTechnicalDocumentHandler,
    clean_technical_document_text as _clean_technical_document_text_impl,
    run_technical_document_extraction as _run_technical_document_extraction_impl,
)
from ...context.execution import ensure_not_cancelled, report_progress
from ...integrations.providers import (
    ModelTarget,
    extract_cerebras_direct,
    extract_with_langextract_optimized,
    resolve_model_target,
)
from ...normalizers.currency import build_currency_db_string, load_currency_db
from ...observability.metrics import RunMetrics, timer


def _resolve_models(model_id: str | None) -> tuple[ModelTarget, ModelTarget]:
    from ...config.runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    return primary_model, fallback_model


def _build_header_metadata(context: str) -> tuple[str, dict]:
    return build_header_metadata(context)


def _collect_invoice_fields(items: list[dict]) -> dict[str, Any]:
    fields = {
        "document_number": None,
        "document_date": None,
        "currency_code": None,
        "currency_name": None,
        "country_sender": None,
    }
    for item in items:
        for key in fields:
            value = item.get(key)
            if fields[key] is None and value not in (None, "", "null", "none"):
                fields[key] = value
    return fields


def _build_review_summary(items: list[dict]) -> dict[str, Any]:
    summary = {
        "review_required_count": 0,
        "high_priority_count": 0,
        "medium_priority_count": 0,
        "positions": [],
        "high_priority_positions": [],
        "medium_priority_positions": [],
    }

    for item in items:
        if not item.get("review_required"):
            continue

        position = item.get("position")
        if position is not None:
            summary["positions"].append(position)

        summary["review_required_count"] += 1
        priority = str(item.get("review_priority") or "").strip().lower()
        if priority == "high":
            summary["high_priority_count"] += 1
            if position is not None:
                summary["high_priority_positions"].append(position)
        elif priority == "medium":
            summary["medium_priority_count"] += 1
            if position is not None:
                summary["medium_priority_positions"].append(position)

    for key in ("positions", "high_priority_positions", "medium_priority_positions"):
        summary[key] = sorted({int(pos) for pos in summary[key] if pos is not None})

    return summary


def _build_top_review_items(items: list[dict], *, limit: int = 10) -> list[dict[str, Any]]:
    review_label_map = {
        "missing_hs_code": "Missing HS code",
        "missing_country_origin": "Missing country",
        "short_description": "Short description",
        "peer_repaired": "Peer repaired",
        "declaration_reference_present": "Has declaration reference",
    }

    def _priority_rank(value: Any) -> int:
        priority = str(value or "").strip().lower()
        if priority == "high":
            return 0
        if priority == "medium":
            return 1
        return 2

    def _reason_count(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _position_value(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**12

    def _review_label(item: dict) -> str | None:
        notes = [
            str(note).strip()
            for note in str(item.get("review_notes") or "").split(",")
            if str(note).strip()
        ]
        if not notes:
            return None
        labels = [review_label_map.get(note, note.replace("_", " ").capitalize()) for note in notes[:2]]
        return " + ".join(labels)

    candidates = [item for item in items if item.get("review_required")]
    candidates.sort(
        key=lambda item: (
            _priority_rank(item.get("review_priority")),
            -_reason_count(item.get("review_reason_count")),
            _position_value(item.get("position")),
        )
    )

    top_items: list[dict[str, Any]] = []
    for item in candidates[:limit]:
        top_items.append(
            {
                "position": item.get("position"),
                "description": item.get("description"),
                "review_priority": item.get("review_priority"),
                "review_reason_count": item.get("review_reason_count"),
                "review_notes": item.get("review_notes"),
                "review_label": _review_label(item),
                "parsing_confidence": item.get("parsing_confidence"),
            }
        )
    return top_items


def _extract_with_timing(context: str, header_context: str, model: ModelTarget) -> dict:
    with timer() as t_llm:
        if model.provider == "cerebras":
            raw_output, annotated_doc, usage = extract_cerebras_direct(
                context,
                model.model_id,
                header_context,
            )
        else:
            raw_output, annotated_doc, usage = extract_with_langextract_optimized(
                context,
                model,
                header_context,
            )
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


def run_invoice_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    metrics = RunMetrics()
    primary_model, fallback_model = _resolve_models(model_id)
    return execute_invoice_extraction(
        ocr_draft=ocr_draft,
        primary_model=primary_model,
        fallback_model=fallback_model,
        metrics=metrics,
        extract_with_timing=_extract_with_timing,
        load_currency_db=load_currency_db,
        build_currency_db_string=build_currency_db_string,
        clean_text=clean_text,
        build_header_metadata=_build_header_metadata,
        extract_structured_pipe_items=extract_structured_pipe_items,
        normalize_invoice_items=normalize_invoice_items,
        merge_normalized_invoice_items=merge_normalized_invoice_items,
        assess_structured_parser=_assess_structured_parser,
        collect_line_level_repair_candidates=_collect_line_level_repair_candidates,
        run_line_level_llm_assist=run_line_level_llm_assist,
        recover_with_structured_items=recover_with_structured_items,
        report_progress=report_progress,
        ensure_not_cancelled=ensure_not_cancelled,
    )


class InvoiceHandler(DocumentHandler):
    document_code = "04021"
    label = "Invoice"
    schema = DocumentSchema(
        result_type="table",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("country_sender", "Country Sender"),
        ),
        item_fields=(
            DocumentFieldSchema("position", "Position", kind="integer"),
            DocumentFieldSchema("part_no", "Part No"),
            DocumentFieldSchema("description", "Description"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("quantity", "Quantity", kind="number"),
            DocumentFieldSchema("unit", "Unit"),
            DocumentFieldSchema("cost", "Cost", kind="number"),
            DocumentFieldSchema("price", "Price", kind="number"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("country_origin_code", "Country Origin Code", kind="integer"),
            DocumentFieldSchema("country_sender", "Country Sender"),
            DocumentFieldSchema("parsing_confidence", "Parsing Confidence"),
            DocumentFieldSchema("review_required", "Review Required"),
            DocumentFieldSchema("review_priority", "Review Priority"),
            DocumentFieldSchema("review_reason_count", "Review Reason Count", kind="integer"),
            DocumentFieldSchema("review_notes", "Review Notes"),
        ),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = run_invoice_extraction(ocr_draft, model_id=model or None)
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": {}, "items": [], "count": 0},
            }

        result = output.get("result", {})
        items = result.get("items", [])
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {
                "fields": _collect_invoice_fields(items),
                "items": items,
                "count": len(items),
                "review_summary": _build_review_summary(items),
                "top_review_items": _build_top_review_items(items),
            },
        }


def clean_technical_document_text(ocr_draft: str) -> str:
    return _clean_technical_document_text_impl(ocr_draft)


def run_technical_document_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    return _run_technical_document_extraction_impl(ocr_draft, model_id=model_id)


class TechnicalDocumentHandler(_RegularTechnicalDocumentHandler):
    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = run_technical_document_extraction(ocr_draft, model_id=model or None)
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": {}, "items": [], "count": 0},
            }

        result = output.get("result", {})
        items = result.get("items", [])
        fields = result.get("fields", {})
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {"fields": fields, "items": items, "count": len(items)},
        }
