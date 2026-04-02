import time
import json
import re
import logging
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from ..base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ...config.runtime import get_runtime_settings
from ...integrations.llm import get_llm_provider
from ...integrations.providers import build_model_spec, resolve_model_target
from ..invoice.invoice_utils import clean_invoice_text

logger = logging.getLogger(__name__)

# --- ПРОМПТ (Твой оригинальный, адаптированный под JSON Mode) ---
TD_SYSTEM_PROMPT = """You are an expert technical-document data extractor.
Extract structured data for ALL products/items listed in the OCR text.

=== FIELDS TO EXTRACT ===
- product_name: item name
- technical_description: description as a single string (if key-value, convert to multiline text)
- hs_code: HS code or null
- model: model/article/SKU
- country_origin: manufacturer country
- document_date: normalize to DD/MM/YYYY; if not found use NO_DATE_FOUND
- document_number: if not found set null

=== RULES ===
1. NO Hallucinations: Only extract what is visible.
2. NO Translation: Keep names and descriptions in the original language.
3. FORMAT: Return ONLY a JSON object with a single key "items" containing the array of objects.
4. If no items found, return {"items": []}.
"""


def validate_technical_document_response(llm_response: str) -> tuple[bool, str, list[dict[str, Any]]]:
    if not llm_response:
        return False, "Empty response", []

    text = str(llm_response).strip()
    text = re.sub(r'^[^{}\[\]]*', '', text)

    parsed_data: Any
    parsed_error = ""
    match_arr = re.search(r'\[.*\]', text, re.DOTALL)
    if match_arr:
        try:
            parsed_data = json.loads(match_arr.group(0))
        except json.JSONDecodeError as exc:
            parsed_data = None
            parsed_error = str(exc)
    else:
        match_obj = re.search(r'\{.*\}', text, re.DOTALL)
        if match_obj:
            try:
                payload = json.loads(match_obj.group(0))
                parsed_data = payload.get("items", payload) if isinstance(payload, dict) else payload
            except json.JSONDecodeError as exc:
                parsed_data = None
                parsed_error = str(exc)
        else:
            parsed_data = None

    if parsed_data is None:
        if len(text) < 200:
            return False, "Model returned a non-JSON refusal or empty text.", []
        return False, f"JSON Parse Error: {parsed_error or 'no JSON object found'}", []

    if not isinstance(parsed_data, list):
        parsed_data = [parsed_data]

    if not parsed_data:
        return True, "", []

    valid_items: list[dict[str, Any]] = []
    for item in parsed_data:
        if not isinstance(item, dict):
            continue

        product_name = str(
            item.get("product_name")
            or item.get("description")
            or ""
        ).strip()
        technical_description = str(
            item.get("technical_description")
            or item.get("description")
            or ""
        ).strip()

        if not product_name and not technical_description:
            continue

        if product_name:
            item["product_name"] = re.sub(r"\s+", " ", product_name)
        else:
            item["product_name"] = None

        if technical_description:
            item["technical_description"] = re.sub(r"\s+", " ", technical_description)
        else:
            item["technical_description"] = None

        hs_code = item.get("hs_code")
        if str(hs_code).strip().lower() in {"none", "null", ""}:
            item["hs_code"] = None

        valid_items.append(item)

    return True, "", valid_items

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
        runtime = get_runtime_settings()
        t_start = time.perf_counter()
        # Используем ту же очистку, что и в инвойсах
        cleaned = clean_invoice_text(ocr_draft)
        
        target = resolve_model_target(model)
        provider = get_llm_provider(target.provider)
        fb_target = resolve_model_target(runtime.llm_model_fallback)
        fb_provider = get_llm_provider(fb_target.provider)

        final_target = target
        fallback_used = False

        # РЕШАЕМ: Целиком или чанками
        if provider.supports_large_context:
            logger.info(f"🚀 TD Strategy: Single-Pass ({target.model_id})")
            single_pass_result, extraction_ok = self._extract_once(
                f"TEXT TO PROCESS:\n{cleaned}",
                provider,
                target,
                fb_provider,
                fb_target,
            )
            final_items = single_pass_result["items"] if single_pass_result else []
            if single_pass_result:
                final_target = single_pass_result["final_target"]
                fallback_used = single_pass_result["fallback_used"]
        else:
            logger.info(f"📦 TD Strategy: Chunking ({target.model_id})")
            max_c = runtime.chunk_size_cerebras if target.provider == "cerebras" else runtime.chunk_size_default
            chunked_result, extraction_ok = self._run_chunked_workflow(
                cleaned,
                provider,
                target,
                fb_provider,
                fb_target,
                max_c,
            )
            final_items = chunked_result["items"]
            final_target = chunked_result["final_target"]
            fallback_used = chunked_result["fallback_used"]

        if not extraction_ok:
            return {
                "status": "failed",
                "document_code": self.document_code,
                "duration": round(time.perf_counter() - t_start, 3),
                "error": "Technical document extraction failed for both primary and fallback models.",
                "result_type": self.result_type,
                "model_id": None,
                "metrics": {
                    "execution": {
                        "primary_model": build_model_spec(target.provider, target.model_id),
                        "fallback_model": (
                            build_model_spec(fb_target.provider, fb_target.model_id)
                            if fb_target != target
                            else None
                        ),
                        "final_model": None,
                        "final_provider": None,
                        "fallback_used": False,
                    }
                },
                "data": {"fields": {"document_number": None, "document_date": None}, "items": [], "count": 0},
            }

        # Постобработка и нормализация дат
        for i, item in enumerate(final_items, 1):
            item["position"] = i
            # Нормализация даты (из твоего оригинального кода)
            item["document_date"] = self._normalize_date(item.get("document_date"))

        # Собираем общие поля документа (из первого товара)
        fields = {"document_number": None, "document_date": None}
        if final_items:
            fields["document_number"] = final_items[0].get("document_number")
            fields["document_date"] = final_items[0].get("document_date")

        return {
            "status": "success",
            "document_code": self.document_code,
            "duration": round(time.perf_counter() - t_start, 3),
            "result_type": self.result_type,
            "model_id": build_model_spec(final_target.provider, final_target.model_id),
            "metrics": {
                "execution": {
                    "primary_model": build_model_spec(target.provider, target.model_id),
                    "fallback_model": (
                        build_model_spec(fb_target.provider, fb_target.model_id)
                        if fb_target != target
                        else None
                    ),
                    "final_model": build_model_spec(final_target.provider, final_target.model_id),
                    "final_provider": final_target.provider,
                    "fallback_used": fallback_used,
                }
            },
            "data": {
                "fields": fields,
                "items": final_items,
                "count": len(final_items)
            }
        }

    def _extract_once(self, text, provider, target, fb_provider, fb_target):
        try:
            raw = provider.generate(TD_SYSTEM_PROMPT, text, target.model_id)
            is_valid, _, items = validate_technical_document_response(raw)
            if is_valid:
                return {"items": items, "final_target": target, "fallback_used": False}, True
        except Exception:
            pass

        try:
            raw = fb_provider.generate(TD_SYSTEM_PROMPT, text, fb_target.model_id)
            is_valid, _, items = validate_technical_document_response(raw)
            if is_valid:
                return {"items": items, "final_target": fb_target, "fallback_used": True}, True
        except Exception:
            pass

        return None, False

    def _run_chunked_workflow(self, text, provider, target, fb_provider, fb_target, max_c):
        # Чанкинг для Cerebras/Ollama
        overlap = 600
        chunks = []
        start = 0
        while start < len(text):
            end = start + max_c
            if end < len(text):
                last_nl = text.rfind('\n', start, end)
                if last_nl > start + 2000: end = last_nl
            chunks.append(text[start:end])
            start = end - overlap if end < len(text) else len(text)

        all_items = []
        any_chunk_succeeded = False
        final_target = target
        fallback_used = False

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    self._process_single_chunk,
                    c,
                    provider,
                    target,
                    fb_provider,
                    fb_target,
                )
                for c in chunks
            ]
            for f in futures:
                chunk_items, chunk_ok, chunk_target, chunk_fallback_used = f.result()
                any_chunk_succeeded = any_chunk_succeeded or chunk_ok
                all_items.extend(chunk_items)
                if chunk_target is not None and chunk_fallback_used:
                    final_target = chunk_target
                    fallback_used = True
        
        # Дедупликация (по имени и модели)
        unique = []
        seen = set()
        for it in all_items:
            slug = f"{str(it.get('product_name')).lower()}_{it.get('model')}"
            if slug not in seen:
                unique.append(it)
                seen.add(slug)
        return {
            "items": unique,
            "final_target": final_target,
            "fallback_used": fallback_used,
        }, any_chunk_succeeded

    def _process_single_chunk(self, chunk, provider, target, fb_provider, fb_target):
        try:
            raw = provider.generate(TD_SYSTEM_PROMPT, chunk, target.model_id)
            is_valid, _, items = validate_technical_document_response(raw)
            if is_valid:
                return items, True, target, False
        except Exception:
            pass
        try:
            raw = fb_provider.generate(TD_SYSTEM_PROMPT, chunk, fb_target.model_id)
            is_valid, _, items = validate_technical_document_response(raw)
            if is_valid:
                return items or [], True, fb_target, True
        except Exception:
            pass
        return [], False, None, False

    def _normalize_date(self, val):
        if not val or str(val).upper() == "NO_DATE_FOUND":
            return None
        # Простая нормализация через регулярку
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", str(val))
        if match:
            d, m, y = match.groups()
            return f"{int(d):02d}/{int(m):02d}/{y}"
        return str(val)
