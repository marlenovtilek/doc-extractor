from __future__ import annotations

from datetime import datetime
import html
import re
import time
from typing import Any

import langextract as lx

from .base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ..config.runtime import get_runtime_settings
from ..integrations.providers import extract_with_langextract_entities, resolve_model_target
from ..observability.metrics import RunMetrics, timer


TRACKED_SIMPLE_DOCUMENT_FIELDS = (
    "document_number",
    "document_date",
    "description",
)

SIMPLE_DOCUMENT_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a document in English or Russian. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the document (if any)
- `document_date` — the date of the document (normalize to DD/MM/YYYY if possible)
- `description` — {desc_instruction}

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""


def clean_object_text(ocr_draft: str) -> str:
    """Normalize OCR text for object-style extraction."""
    text = html.unescape(ocr_draft or "")
    if not text.strip():
        return ""

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(p|div|span|table|tbody|thead|tr|td|th)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", " ")

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t|")
        if not line:
            continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def normalize_object_date(value: str | None) -> str | None:
    """Normalize a date into DD/MM/YYYY when possible."""
    text = (value or "").strip()
    if not text:
        return None

    direct_formats = (
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
    )
    for fmt in direct_formats:
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue

    compact = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if compact:
        day, month, year = compact.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"

    return text


def aggregate_object_fields(
    extractions: list[dict[str, object]],
    tracked_fields: tuple[str, ...],
    *,
    array_fields: tuple[str, ...] = (),
    default_current_date_if_missing: bool = False,
) -> dict[str, object]:
    """Aggregate LangExtract entities into a single object-style document."""
    fields: dict[str, object] = {name: None for name in tracked_fields}
    arrays: dict[str, list[str]] = {name: [] for name in array_fields}

    for extraction in extractions:
        extraction_class = str(extraction.get("extraction_class") or "").strip()
        extraction_text = str(extraction.get("extraction_text") or "").strip()
        if not extraction_class or not extraction_text:
            continue

        if extraction_class in arrays:
            if extraction_text not in arrays[extraction_class]:
                arrays[extraction_class].append(extraction_text)
            continue

        if extraction_class in fields and not fields[extraction_class]:
            fields[extraction_class] = extraction_text

    if "document_date" in fields:
        normalized_date = normalize_object_date(fields.get("document_date"))  # type: ignore[arg-type]
        if normalized_date is None and default_current_date_if_missing:
            normalized_date = datetime.now().strftime("%d/%m/%Y")
        fields["document_date"] = normalized_date

    for name, values in arrays.items():
        fields[name] = values or None
    return fields


def validate_object_fields(
    fields: dict[str, object],
    tracked_fields: tuple[str, ...],
    *,
    array_fields: tuple[str, ...] = (),
    empty_error: str,
) -> tuple[bool, str]:
    """Validate a normalized object-style document."""
    if not fields:
        return False, empty_error

    if not any(fields.get(name) for name in tracked_fields):
        return False, empty_error

    for key in array_fields:
        value = fields.get(key)
        if value is not None:
            if not isinstance(value, list):
                return False, f"'{key}' must be a list or null"
            if any(not isinstance(item, str) for item in value):
                return False, f"'{key}' must contain only strings"

    for key in tracked_fields:
        if key in array_fields:
            continue
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            return False, f"'{key}' must be a string or null"

    return True, ""


def compute_object_field_fill_rates(
    fields: dict[str, object],
    tracked_fields: tuple[str, ...],
) -> dict[str, float]:
    """Return per-field fill rates for object-style extraction."""
    rates: dict[str, float] = {}
    for name in tracked_fields:
        value = fields.get(name)
        if isinstance(value, list):
            rates[name] = 1.0 if value else 0.0
        else:
            rates[name] = 1.0 if value not in (None, "", "null", "none") else 0.0
    return rates


def _resolve_object_model(model_id: str | None, *, label: str):
    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    if primary_model.provider != "cerebras":
        return primary_model, False

    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    if fallback_model.provider == "cerebras":
        raise ValueError(
            f"{label} extraction requires a LangExtract-backed model "
            "(gemini, openai, or ollama)."
        )
    return fallback_model, True


def run_object_document_extraction(
    ocr_draft: str,
    *,
    model_id: str | None,
    prompt: str,
    examples: list[lx.data.ExampleData],
    tracked_fields: tuple[str, ...],
    array_fields: tuple[str, ...] = (),
    default_current_date_if_missing: bool = False,
    empty_error: str,
    label: str,
) -> dict:
    """Shared object-style extraction flow for non-tabular documents."""
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    with timer() as t_clean:
        context = clean_object_text(ocr_draft)
    metrics.t_clean_s = t_clean[0]

    target_model, implicit_fallback = _resolve_object_model(model_id, label=label)
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
            prompt_description=prompt,
            examples=examples,
        )
    metrics.t_primary_llm_s = t_llm[0]
    if usage:
        metrics.token_usage["primary"] = usage

    with timer() as t_validate:
        fields = aggregate_object_fields(
            extractions,
            tracked_fields,
            array_fields=array_fields,
            default_current_date_if_missing=default_current_date_if_missing,
        )
        is_valid, error = validate_object_fields(
            fields,
            tracked_fields,
            array_fields=array_fields,
            empty_error=empty_error,
        )
    metrics.t_validate_s = t_validate[0]
    metrics.primary_valid = is_valid

    if not is_valid:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": error or f"{label} extraction failed",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    metrics.field_fill_rates = compute_object_field_fill_rates(fields, tracked_fields)
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"fields": fields, "items": [], "count": 0},
        "metrics": metrics.to_dict(),
        "model_id": target_model.model_id,
    }


class BaseObjectHandler(DocumentHandler):
    """Thin adapter to expose object-style pipelines through the registry."""

    def _empty_fields(self) -> dict[str, object]:
        return {field.name: None for field in self.schema.fields}

    def _wrap_object_output(self, output: dict[str, Any]) -> dict[str, Any]:
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": self._empty_fields(), "items": [], "count": 0},
            }

        result = output.get("result", {})
        fields = result.get("fields", self._empty_fields())
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {
                "fields": fields,
                "items": [],
                "count": 0,
            },
        }


class ConfiguredObjectHandler(BaseObjectHandler):
    """Declarative handler for standard object-style documents."""

    prompt: str = ""
    examples: tuple[lx.data.ExampleData, ...] = ()
    tracked_fields: tuple[str, ...] = ()
    array_fields: tuple[str, ...] = ()
    default_current_date_if_missing: bool = False
    empty_error: str | None = None

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = run_object_document_extraction(
            ocr_draft,
            model_id=model or None,
            prompt=self.prompt,
            examples=list(self.examples),
            tracked_fields=self.tracked_fields,
            array_fields=self.array_fields,
            default_current_date_if_missing=self.default_current_date_if_missing,
            empty_error=self.empty_error or f"No {self.label} fields extracted",
            label=self.label,
        )
        return self._wrap_object_output(output)


class SimpleObjectHandler(ConfiguredObjectHandler):
    """Shared handler for simple three-field object documents."""

    desc_instruction: str = (
        "A concise description summarizing the document (1–2 sentences, **keep in Russian**)"
    )
    examples: tuple = ()
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    @property
    def prompt(self) -> str:
        return SIMPLE_DOCUMENT_PROMPT.format(desc_instruction=self.desc_instruction)


__all__ = [
    "BaseObjectHandler",
    "ConfiguredObjectHandler",
    "SIMPLE_DOCUMENT_PROMPT",
    "SimpleObjectHandler",
    "TRACKED_SIMPLE_DOCUMENT_FIELDS",
    "aggregate_object_fields",
    "clean_object_text",
    "compute_object_field_fill_rates",
    "normalize_object_date",
    "run_object_document_extraction",
    "validate_object_fields",
]
