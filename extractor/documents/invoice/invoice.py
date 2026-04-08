import time
import re
import logging
from typing import Any
from collections import deque
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

        logger.info(f"📦 Invoice Strategy: Provider-Chunking ({target.model_id})")
        max_c, max_workers = self._chunk_settings_for_provider(rt, target.provider)
        chunked_result = self._run_chunked_workflow(
            cleaned,
            provider,
            target,
            fb_provider,
            fb_target,
            max_c,
            max_workers,
        )
        final_items = chunked_result["items"]
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

    def _chunk_settings_for_provider(self, runtime, provider_name: str) -> tuple[int, int]:
        size_by_provider = {
            "gemini": runtime.invoice_chunk_size_gemini,
            "openai": runtime.invoice_chunk_size_openai,
            "ollama": runtime.invoice_chunk_size_ollama,
            "cerebras": runtime.invoice_chunk_size_cerebras,
            "vllm": runtime.invoice_chunk_size_vllm,
        }
        if provider_name == "cerebras":
            return size_by_provider["cerebras"], 5
        if provider_name == "vllm":
            return size_by_provider["vllm"], runtime.invoice_vllm_max_workers
        return size_by_provider.get(provider_name, runtime.chunk_size_default), 5

    def _run_chunked_workflow(self, text, provider, target, fb_provider, fb_target, max_c, max_workers):
        runtime = get_runtime_settings()
        overlap = self._chunk_overlap_for_provider(runtime, target.provider, max_c)
        chunks = self._split_invoice_chunks(text, max_c, overlap)

        all_raw = []

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [
                ex.submit(
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
                chunk_items = f.result()
                all_raw.extend(chunk_items)

        unique = self._dedupe_invoice_rows(all_raw)
        return {"items": unique}

    def _chunk_overlap_for_provider(self, runtime, provider_name: str, max_c: int) -> int:
        if provider_name == "vllm":
            raw_overlap = getattr(runtime, "invoice_chunk_overlap_vllm", 100)
        else:
            raw_overlap = getattr(runtime, "invoice_chunk_overlap_default", 600)
        return max(0, min(raw_overlap, max(0, max_c - 1)))

    def _split_invoice_chunks(self, text: str, max_c: int, overlap: int = 600) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + max_c, len(text))
            if end < len(text):
                last_nl = text.rfind("\n", start, end)
                if last_nl > start + (max_c // 2):
                    end = last_nl
            chunks.append(text[start:end])
            start = end - overlap if end < len(text) else len(text)
        return chunks

    def _dedupe_invoice_rows(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        recent_fingerprints: deque[str] = deque(maxlen=25)

        for item in items:
            fingerprint = self._invoice_item_fingerprint(item)
            if fingerprint in recent_fingerprints:
                continue
            unique.append(item)
            recent_fingerprints.append(fingerprint)

        return unique

    def _invoice_item_fingerprint(self, item: dict[str, Any]) -> str:
        def _norm(value: Any) -> str:
            text = str(value or "").strip().lower()
            text = re.sub(r"\s+", " ", text)
            return text

        return "|".join(
            (
                _norm(item.get("description")),
                _norm(item.get("quantity")),
                _norm(item.get("price")),
                _norm(item.get("cost")),
            )
        )

    def _process_single_chunk(self, chunk, provider, target, fb_provider, fb_target):
        user_prompt = INVOICE_USER_TEMPLATE.format(ocr_text=chunk)
        try:
            raw = provider.generate(INVOICE_SYSTEM_PROMPT, user_prompt, target.model_id)
            v, reason, items = validate_and_format_invoice(raw)
            if v and items:
                return items
        except Exception:
            pass

        try:
            raw = fb_provider.generate(INVOICE_SYSTEM_PROMPT, user_prompt, fb_target.model_id)
            _, _, items = validate_and_format_invoice(raw)
            return items or []
        except Exception:
            return []
