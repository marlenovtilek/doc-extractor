from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any

import langextract as lx

from ..base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ...integrations.providers import extract_with_langextract_entities, resolve_model_target
from ...observability.metrics import RunMetrics, compute_field_fill_rates, timer


TD_EXTRACTION_PROMPT = """
# ROLE
You are an expert technical-document data extractor.

# TASK
You are given OCR text from a Technical Specification document. The text may have
mixed formats, irregular structure, and OCR artifacts.

Extract structured data for ALL products/items listed in the document.

For each product found, extract:
- `product_name` — product/item name
- `technical_description` — technical description as a single string
- `hs_code` — HS code, if not found set null
- `model` — model / article / SKU
- `country_origin` — manufacturer or country of origin
- `document_date` — document date, normalize to DD/MM/YYYY when possible; if not
  found use exactly `NO_DATE_FOUND`
- `document_number` — document number, if not found set null

# RULES
- Ignore headers, footers, signatures, stamps, and decorative boilerplate.
- Normalize dates when possible.
- If a field cannot be found for a specific item, set it to null.
- `technical_description` must always be a single plain string, never an object.
- If specifications are key-value, convert them to plain multiline text.
- Keep original source language.
"""

TD_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Technical Specification No. TD-55\n"
            "Date: 09/10/2025\n"
            "1. Product: Pressure Sensor PS-200\n"
            "Specifications: Range 0-10 bar; Material stainless steel; Output 4-20mA\n"
            "HS code: 9026202000\n"
            "Origin: Germany\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="technical_document_item",
                extraction_text="Pressure Sensor PS-200",
                attributes={
                    "product_name": "Pressure Sensor PS-200",
                    "technical_description": "Range: 0-10 bar\nMaterial: stainless steel\nOutput: 4-20mA",
                    "hs_code": "9026202000",
                    "model": "PS-200",
                    "country_origin": "Germany",
                    "document_date": "09/10/2025",
                    "document_number": "TD-55",
                },
            )
        ],
    ),
    lx.data.ExampleData(
        text=(
            "SPECIFICATION REF. TS-88/24\n"
            "Issued on 2024-11-18\n"
            "Item: Cable Gland M20\n"
            "Description: Polyamide cable gland for industrial cabinet assembly\n"
            "Country of origin: China\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="technical_document_item",
                extraction_text="Cable Gland M20",
                attributes={
                    "product_name": "Cable Gland M20",
                    "technical_description": "Polyamide cable gland for industrial cabinet assembly",
                    "hs_code": None,
                    "model": "M20",
                    "country_origin": "China",
                    "document_date": "18/11/2024",
                    "document_number": "TS-88/24",
                },
            )
        ],
    ),
]

TD_ITEM_FIELDS = (
    "product_name",
    "technical_description",
    "hs_code",
    "model",
    "country_origin",
    "document_date",
    "document_number",
)


def clean_technical_document_text(ocr_draft: str) -> str:
    text = html.unescape(ocr_draft or "")
    if not text.strip():
        return ""

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(p|div|span|table|tbody|thead|tr|td|th)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", " ")
    text = text.replace("\xa0", " ")

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t|")
        if not line:
            continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _td_to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = re.sub(r"[ \t]+", " ", str(value)).strip()
        return text or None
    return None


def _td_flatten_to_lines(value: object, lines: list[str], parent_key: str = "") -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for key, inner_value in value.items():
            key_text = _td_to_text(key) or parent_key
            if isinstance(inner_value, (dict, list)):
                _td_flatten_to_lines(inner_value, lines, key_text)
            else:
                value_text = _td_to_text(inner_value)
                if value_text:
                    lines.append(f"{key_text}: {value_text}" if key_text else value_text)
        return
    if isinstance(value, list):
        for inner_value in value:
            if isinstance(inner_value, (dict, list)):
                _td_flatten_to_lines(inner_value, lines, parent_key)
            else:
                value_text = _td_to_text(inner_value)
                if value_text:
                    lines.append(f"{parent_key}: {value_text}" if parent_key else value_text)
        return
    value_text = _td_to_text(value)
    if value_text:
        lines.append(f"{parent_key}: {value_text}" if parent_key else value_text)


def _td_description_to_text(value: object) -> str | None:
    scalar = _td_to_text(value)
    if scalar is not None:
        return scalar
    if isinstance(value, (dict, list)):
        lines: list[str] = []
        _td_flatten_to_lines(value, lines)
        text = "\n".join(line for line in lines if line.strip()).strip()
        return text or None
    return None


def _td_normalize_date(value: object) -> str:
    text = _td_to_text(value)
    if not text or text.upper() == "NO_DATE_FOUND":
        return datetime.now().strftime("%d/%m/%Y")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    compact = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if compact:
        day, month, year = compact.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"
    return text


def _resolve_td_model(model_id: str | None):
    from ...config.runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    if primary_model.provider != "cerebras":
        return primary_model, False

    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    if fallback_model.provider == "cerebras":
        raise ValueError(
            "Technical document extraction requires a LangExtract-backed model "
            "(gemini, openai, or ollama)."
        )
    return fallback_model, True


def _normalize_td_items(extractions: list[dict[str, object]]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for extraction in extractions:
        attributes = extraction.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}

        item: dict[str, object] = {field: None for field in TD_ITEM_FIELDS}
        item.update(attributes)
        item["product_name"] = _td_to_text(item.get("product_name")) or _td_to_text(
            extraction.get("extraction_text")
        )
        item["technical_description"] = _td_description_to_text(item.get("technical_description"))
        item["hs_code"] = _td_to_text(item.get("hs_code"))
        item["model"] = _td_to_text(item.get("model"))
        item["country_origin"] = _td_to_text(item.get("country_origin"))
        item["document_date"] = _td_normalize_date(item.get("document_date"))
        item["document_number"] = _td_to_text(item.get("document_number"))

        if item["product_name"] or item["technical_description"]:
            items.append(item)
    return items


def _validate_td_items(items: list[dict[str, object]]) -> tuple[bool, str]:
    if not items:
        return False, "No technical document items extracted"
    for item in items:
        for key in TD_ITEM_FIELDS:
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                return False, f"'{key}' must be a string or null"
    return True, ""


def _build_td_fields(items: list[dict[str, object]]) -> dict[str, object]:
    fields = {"document_number": None, "document_date": None}
    for item in items:
        if not fields["document_number"] and item.get("document_number"):
            fields["document_number"] = item["document_number"]
        if not fields["document_date"] and item.get("document_date"):
            fields["document_date"] = item["document_date"]
    return fields


def run_technical_document_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    with timer() as t_clean:
        context = clean_technical_document_text(ocr_draft)
    metrics.t_clean_s = t_clean[0]

    target_model, implicit_fallback = _resolve_td_model(model_id)
    metrics.fallback_used = implicit_fallback

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": "Empty OCR text",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    with timer() as t_llm:
        extractions, _annotated_doc, usage = extract_with_langextract_entities(
            context,
            target_model,
            prompt_description=TD_EXTRACTION_PROMPT,
            examples=TD_EXAMPLES,
        )
    metrics.t_primary_llm_s = t_llm[0]
    if usage:
        metrics.token_usage["primary"] = usage

    with timer() as t_validate:
        items = _normalize_td_items(extractions)
        is_valid, error = _validate_td_items(items)
    metrics.t_validate_s = t_validate[0]
    metrics.primary_valid = is_valid

    if not is_valid:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": error or "Technical document extraction failed",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    metrics.items_extracted = len(items)
    metrics.field_fill_rates = compute_field_fill_rates(items)
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"fields": _build_td_fields(items), "items": items, "count": len(items)},
        "metrics": metrics.to_dict(),
        "model_id": target_model.model_id,
    }


class TechnicalDocumentHandler(DocumentHandler):
    document_code = "09022"
    label = "Technical Document"
    schema = DocumentSchema(
        result_type="table",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
        ),
        item_fields=(
            DocumentFieldSchema("product_name", "Product Name"),
            DocumentFieldSchema("technical_description", "Technical Description"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("model", "Model"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("document_number", "Document Number"),
        ),
    )

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
