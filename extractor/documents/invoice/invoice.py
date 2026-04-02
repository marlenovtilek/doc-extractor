import time
import re
import logging
import json
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from extractor.documents.base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from extractor.integrations.llm import get_llm_provider
from extractor.integrations.providers import build_model_spec, resolve_model_target
from extractor.config.runtime import get_runtime_settings
from extractor.normalizers.currency import finalize_items, infer_currency_from_text, load_currency_db

from .invoice_utils import clean_invoice_text, validate_and_format_invoice
from .invoice_prompt import INVOICE_SYSTEM_PROMPT, INVOICE_USER_TEMPLATE
from .invoice_validator import extract_header_fields

logger = logging.getLogger(__name__)

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
            DocumentFieldSchema("description", "Description"),
            DocumentFieldSchema("quantity", "Quantity"),
            DocumentFieldSchema("unit", "Unit"),
            DocumentFieldSchema("cost", "Cost"),
            DocumentFieldSchema("price", "Price"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("country_origin_code", "Country Origin Code"),
        ),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        rt = get_runtime_settings()
        t_start = time.perf_counter()
        cleaned = clean_invoice_text(ocr_draft)
        
        target = resolve_model_target(model)
        provider = get_llm_provider(target.provider)
        fb_target = resolve_model_target(rt.llm_model_fallback)
        fb_provider = get_llm_provider(fb_target.provider)

        # Решаем стратегию на основе провайдера
        if provider.supports_large_context:
            logger.info(f"🚀 Strategy: Single-Pass ({target.model_id})")
            user_prompt = INVOICE_USER_TEMPLATE.format(ocr_text=cleaned)
            final_items, final_target, fallback_used = self._extract_single_pass(
                user_prompt,
                provider,
                target,
                fb_provider,
                fb_target,
            )
        else:
            logger.info(f"📦 Strategy: Chunking ({target.model_id})")
            # Передаем настройки чанка из Runtime
            max_c = rt.chunk_size_cerebras if target.provider == "cerebras" else rt.chunk_size_default
            final_items = self._run_chunked_workflow(cleaned, provider, target.model_id, max_c)
            final_target = target
            fallback_used = False

        currency_db = load_currency_db()
        final_items = finalize_items(final_items, currency_db)
        header_fields = extract_header_fields(final_items)
        currency_code = header_fields.get("currency_code")
        currency_name = header_fields.get("currency_name")
        if not currency_code and not currency_name:
            currency_code, currency_name = infer_currency_from_text(cleaned, currency_db)
            header_fields["currency_code"] = currency_code
            header_fields["currency_name"] = currency_name
        if currency_code or currency_name:
            for item in final_items:
                if not item.get("currency_code") and currency_code:
                    item["currency_code"] = currency_code
                if not item.get("currency_name") and currency_name:
                    item["currency_name"] = currency_name

        # Очистка и нумерация
        for i, item in enumerate(final_items, 1):
            item["position"] = i
            d = str(item.get("description", ""))
            item["description"] = re.sub(r'<[^>]*>', ' ', d).strip(" .,").strip()
            item.pop("document_number", None)
            item.pop("document_date", None)
            item.pop("country_sender", None)

        return {
            "status": "success", "document_code": self.document_code,
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
                "fields": {
                    "document_number": header_fields.get("document_number"),
                    "document_date": header_fields.get("document_date"),
                    "currency_code": header_fields.get("currency_code"),
                    "currency_name": header_fields.get("currency_name"),
                    "country_sender": header_fields.get("country_sender"),
                },
                "items": final_items,
                "count": len(final_items),
            }
        }

    def _extract_single_pass(self, user_prompt, provider, target, fb_provider, fb_target):
        attempts = [(target, provider, False)]
        if fb_target != target:
            attempts.append((fb_target, fb_provider, True))

        last_error: Exception | None = None
        for attempt_target, attempt_provider, used_fallback in attempts:
            try:
                raw = attempt_provider.generate(
                    INVOICE_SYSTEM_PROMPT,
                    user_prompt,
                    attempt_target.model_id,
                )
            except Exception as exc:
                last_error = exc
                continue

            is_valid, _, items = validate_and_format_invoice(raw)
            if is_valid and items:
                return items, attempt_target, used_fallback

        if last_error is not None:
            raise last_error
        raise ValueError("No invoice items extracted by either primary or fallback model.")

    def _run_chunked_workflow(self, text, provider, model_id, max_c):
        overlap = 600
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + max_c, len(text))
            if end < len(text):
                last_nl = text.rfind('\n', start, end)
                if last_nl > start + (max_c // 2): end = last_nl
            chunks.append(text[start:end])
            start = end - overlap if end < len(text) else len(text)

        all_raw = []
        # Fallback модель тоже берем из настроек
        fb_target = resolve_model_target(get_runtime_settings().llm_model_fallback)
        fb_provider = get_llm_provider(fb_target.provider)

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(self._process_single_chunk, c, provider, model_id, fb_provider, fb_target.model_id) for c in chunks]
            for f in futures: all_raw.extend(f.result())

        # Дедупликация нахлестов по цифрам (Кол-во + Цена)
        unique = []
        for it in all_raw:
            fprint = f"{it.get('quantity')}_{it.get('price')}"
            if not unique or f"{unique[-1].get('quantity')}_{unique[-1].get('price')}" != fprint:
                unique.append(it)
        return unique

    def _process_single_chunk(self, chunk, provider, m_id, fb_provider, fb_m_id):
        user_prompt = INVOICE_USER_TEMPLATE.format(ocr_text=chunk)
        try:
            raw = provider.generate(INVOICE_SYSTEM_PROMPT, user_prompt, m_id)
            v, _, items = validate_and_format_invoice(raw)
            if v and items: return items
        except: pass
        try:
            raw = fb_provider.generate(INVOICE_SYSTEM_PROMPT, user_prompt, fb_m_id)
            _, _, items = validate_and_format_invoice(raw)
            return items or []
        except: return []
