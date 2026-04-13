import time
import re
import logging
import json
from typing import Any
from datetime import datetime

from .base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ..config.runtime import get_runtime_settings
from ..integrations.llm import get_llm_provider
from ..integrations.providers import build_model_spec, resolve_model_target
from .invoice.invoice_utils import clean_invoice_text

logger = logging.getLogger(__name__)

# Константа, которую ищут другие файлы
TRACKED_SIMPLE_DOCUMENT_FIELDS = ("document_number", "document_date", "description")

SIMPLE_DOCUMENT_PROMPT = """You are an expert legal-document data extractor.
Extract fields from the OCR text into a structured JSON object.

=== FIELDS TO EXTRACT ===
{fields_description}

=== RULES ===
1. NO Hallucinations: Only extract what is visible.
2. NO Translation: Keep descriptions in the original language (Russian).
3. FORMAT: Return ONLY a raw JSON object.
4. If a field is not found, set it to null.
"""

def normalize_object_date(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text: return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError: continue
    compact = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if compact:
        d, m, y = compact.groups()
        return f"{int(d):02d}/{int(m):02d}/{y}"
    return text

def extract_json_object(text: str) -> dict:
    try:
        clean_json = re.sub(r'^[^{]*', '', text)
        clean_json = re.sub(r'[^}]*$', '', clean_json)
        return json.loads(clean_json)
    except: return {}


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "null", "none"}
    return True

class BaseObjectHandler(DocumentHandler):
    def _build_final_fields(self, extracted_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        final_fields: dict[str, Any] = {}
        has_meaningful_model_value = False

        for f in self.schema.fields:
            raw_val = extracted_data.get(f.name)
            if _has_meaningful_value(raw_val):
                has_meaningful_model_value = True

            val = raw_val
            if f.name == "document_date":
                val = normalize_object_date(val)
                if not val and getattr(self, "default_current_date_if_missing", False):
                    val = datetime.now().strftime("%d/%m/%Y")
            final_fields[f.name] = val

        return final_fields, has_meaningful_model_value

    def extract(
        self,
        *,
        ocr_draft: str,
        model: str | None = None,
        source_file_path: str | None = None,
    ) -> dict[str, Any]:
        t_start = time.perf_counter()
        cleaned = clean_invoice_text(ocr_draft)
        target = resolve_model_target(model)
        provider = get_llm_provider(target.provider)
        fallback_target = resolve_model_target(get_runtime_settings().llm_model_fallback)
        fallback_provider = get_llm_provider(fallback_target.provider)

        # Если в классе прописан свой prompt — используем его, иначе строим из схемы
        if hasattr(self, 'prompt') and self.prompt:
            sys_prompt = self.prompt
        else:
            fields_desc = ""
            for f in self.schema.fields:
                instr = getattr(self, 'desc_instruction', f.label) if f.name == "description" else f.label
                fields_desc += f"- {f.name}: {instr}\n"
            sys_prompt = SIMPLE_DOCUMENT_PROMPT.format(fields_description=fields_desc)

        attempts = [(target, provider, False)]
        if fallback_target != target:
            attempts.append((fallback_target, fallback_provider, True))

        selected_target = None
        selected_fields: dict[str, Any] | None = None
        fallback_used = False
        attempt_errors: list[str] = []

        for attempt_target, attempt_provider, used_fallback in attempts:
            try:
                raw = attempt_provider.generate(
                    sys_prompt,
                    f"TEXT:\n{cleaned}",
                    attempt_target.model_id,
                )
            except Exception as exc:
                attempt_errors.append(f"{build_model_spec(attempt_target.provider, attempt_target.model_id)}: {exc}")
                continue

            extracted_data = extract_json_object(raw)
            if not isinstance(extracted_data, dict):
                extracted_data = {}
            if raw.strip() and not extracted_data:
                attempt_errors.append(
                    f"{build_model_spec(attempt_target.provider, attempt_target.model_id)}: "
                    f"{getattr(self, 'empty_error', f'Failed to parse structured response for {self.label}.')}"
                )
                continue

            final_fields, has_meaningful_model_value = self._build_final_fields(extracted_data)
            if has_meaningful_model_value:
                selected_target = attempt_target
                selected_fields = final_fields
                fallback_used = used_fallback
                break

            attempt_errors.append(
                f"{build_model_spec(attempt_target.provider, attempt_target.model_id)}: "
                f"{getattr(self, 'empty_error', f'No fields extracted for {self.label}.')}"
            )

        if selected_target is None or selected_fields is None:
            logger.error(f"LLM fail for {self.document_code}: {'; '.join(attempt_errors)}")
            return {
                "status": "failed",
                "document_code": self.document_code,
                "duration": round(time.perf_counter() - t_start, 3),
                "error": attempt_errors[-1] if attempt_errors else f"Failed to extract fields for {self.label}.",
                "result_type": self.result_type,
                "model_id": None,
                "metrics": {
                    "execution": {
                        "primary_model": build_model_spec(target.provider, target.model_id),
                        "fallback_model": (
                            build_model_spec(fallback_target.provider, fallback_target.model_id)
                            if fallback_target != target
                            else None
                        ),
                        "final_model": None,
                        "final_provider": None,
                        "fallback_used": False,
                    }
                },
                "data": {"fields": {}, "items": [], "count": 0},
            }

        model_spec = build_model_spec(selected_target.provider, selected_target.model_id)
        return {
            "status": "success",
            "document_code": self.document_code,
            "duration": round(time.perf_counter() - t_start, 3),
            "result_type": self.result_type,
            "model_id": model_spec,
            "metrics": {
                "execution": {
                    "primary_model": build_model_spec(target.provider, target.model_id),
                    "fallback_model": (
                        build_model_spec(fallback_target.provider, fallback_target.model_id)
                        if fallback_target != target
                        else None
                    ),
                    "final_model": model_spec,
                    "final_provider": selected_target.provider,
                    "fallback_used": fallback_used,
                }
            },
            "data": {"fields": selected_fields, "items": [], "count": 0},
        }

class ConfiguredObjectHandler(BaseObjectHandler):
    desc_instruction: str = "concise summary in Russian"
