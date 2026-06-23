import time
import re
import logging
from typing import Any
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from extractor.base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from extractor.llm import get_llm_provider
from extractor.providers import build_model_spec, resolve_model_target
from extractor.runtime import get_runtime_settings
from extractor.currency import finalize_items, infer_currency_from_text, load_currency_db
from extractor.pdf_media import build_visual_inputs

from .invoice_utils import clean_invoice_text, validate_and_format_invoice
from .invoice_prompt import INVOICE_SYSTEM_PROMPT, INVOICE_USER_TEMPLATE
from .invoice_scan_layout import extract_scan_table_invoice
from .invoice_vlm_prompt import INVOICE_VLM_SYSTEM_PROMPT, INVOICE_VLM_USER_PROMPT
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

    def extract(
        self,
        *,
        ocr_draft: str,
        model: str | None = None,
        source_file_path: str | None = None,
    ) -> dict[str, Any]:
        rt = get_runtime_settings()
        t_start = time.perf_counter()
        cleaned = clean_invoice_text(ocr_draft)
        
        target = resolve_model_target(model)
        provider = get_llm_provider(target.provider)
        fb_target = resolve_model_target(rt.llm_model_fallback)
        fb_provider = get_llm_provider(fb_target.provider)

        final_target = target
        fallback_used = False
        helper_target = None
        helper_mode = None
        helper_items_count = 0
        helper_updates = 0
        scan_helper_mode = None
        scan_helper_items_count = 0
        scan_helper_updates = 0

        if target.provider == "vlm":
            if not source_file_path:
                return {
                    "status": "failed",
                    "document_code": self.document_code,
                    "duration": round(time.perf_counter() - t_start, 3),
                    "error": "VLM invoice extraction requires source_file_path pointing to a PDF or image file.",
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
                    "data": {"fields": {}, "items": [], "count": 0},
                }

            logger.info(f"📦 Invoice Strategy: VLM-Visual ({target.model_id})")
            final_items = self._run_vlm_workflow(
                source_file_path,
                provider,
                target,
                rt,
            )
            if not final_items and fb_target != target:
                logger.warning(
                    "Invoice VLM pass returned no items for %s; falling back to %s",
                    build_model_spec(target.provider, target.model_id),
                    build_model_spec(fb_target.provider, fb_target.model_id),
                )
                if fb_target.provider == "vlm" and source_file_path:
                    final_items = self._run_vlm_workflow(
                        source_file_path,
                        fb_provider,
                        fb_target,
                        rt,
                    )
                else:
                    max_c, max_workers = self._chunk_settings_for_provider(rt, fb_target.provider)
                    chunked_result = self._run_chunked_workflow(
                        cleaned,
                        fb_provider,
                        fb_target,
                        fb_provider,
                        fb_target,
                        max_c,
                        max_workers,
                    )
                    final_items = chunked_result["items"]
                if final_items:
                    final_target = fb_target
                    fallback_used = True

            final_items, scan_helper_mode, scan_helper_updates, scan_helper_items_count = self._apply_scan_table_helper(
                final_items=final_items,
                cleaned_ocr=cleaned,
            )
        else:
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

            final_items, scan_helper_mode, scan_helper_updates, scan_helper_items_count = self._apply_scan_table_helper(
                final_items=final_items,
                cleaned_ocr=cleaned,
            )
            final_items, helper_target, helper_mode, helper_updates, helper_items_count = self._apply_vlm_helper(
                final_items=final_items,
                source_file_path=source_file_path,
                runtime=rt,
            )
            if helper_mode == "rescue" and helper_target is not None:
                final_target = helper_target

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
                    "vlm_helper_model": (
                        build_model_spec(helper_target.provider, helper_target.model_id)
                        if helper_target is not None
                        else None
                    ),
                    "vlm_helper_mode": helper_mode,
                    "vlm_helper_items_count": helper_items_count,
                    "vlm_helper_updates": helper_updates,
                    "scan_helper_mode": scan_helper_mode,
                    "scan_helper_items_count": scan_helper_items_count,
                    "scan_helper_updates": scan_helper_updates,
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

    def _run_vlm_workflow(self, source_file_path, provider, target, runtime):
        visual_inputs = build_visual_inputs(
            source_file_path,
            pdf_dpi=runtime.vlm_pdf_render_dpi,
            max_pages=runtime.vlm_max_pages,
        )
        pages_per_prompt = max(1, runtime.vlm_pages_per_prompt)
        all_raw: list[dict[str, Any]] = []

        for start in range(0, len(visual_inputs), pages_per_prompt):
            page_batch = visual_inputs[start:start + pages_per_prompt]
            raw = provider.generate_from_images(
                INVOICE_VLM_SYSTEM_PROMPT,
                INVOICE_VLM_USER_PROMPT,
                page_batch,
                target.model_id,
            )
            valid, _, items = validate_and_format_invoice(raw)
            if valid and items:
                all_raw.extend(items)

        # For visual extraction we prefer recall over aggressive duplicate
        # suppression. Page-by-page VLM runs were dropping too many real rows
        # when multiple items shared similar description/price patterns.
        return all_raw

    def _apply_scan_table_helper(self, *, final_items, cleaned_ocr):
        scan_result = extract_scan_table_invoice(cleaned_ocr)
        helper_items = scan_result.get("items", [])
        helper_items_count = len(helper_items)

        if not helper_items:
            return final_items, None, 0, 0

        if not final_items:
            logger.info(
                "Invoice scan-table helper rescued empty primary result with %s items",
                helper_items_count,
            )
            return helper_items, "rescue", 0, helper_items_count

        if helper_items_count > len(final_items) + max(3, len(final_items) // 10):
            merged_items, updates = self._merge_items_with_vlm_helper(helper_items, final_items)
            logger.info(
                "Invoice scan-table helper override: primary_items=%s, helper_items=%s, updated_fields=%s",
                len(final_items),
                helper_items_count,
                updates,
            )
            return merged_items, "override", updates, helper_items_count

        merged_items, updates = self._merge_items_with_vlm_helper(final_items, helper_items)
        helper_mode = "enrich" if updates else "noop"
        logger.info(
            "Invoice scan-table helper %s: primary_items=%s, helper_items=%s, updated_fields=%s",
            helper_mode,
            len(final_items),
            helper_items_count,
            updates,
        )
        return merged_items, helper_mode, updates, helper_items_count

    def _apply_vlm_helper(self, *, final_items, source_file_path, runtime):
        if not source_file_path:
            return final_items, None, None, 0, 0

        helper_target = self._resolve_vlm_helper_target(runtime)
        if helper_target is None:
            return final_items, None, None, 0, 0

        try:
            helper_provider = get_llm_provider(helper_target.provider)
            helper_items = self._run_vlm_workflow(
                source_file_path,
                helper_provider,
                helper_target,
                runtime,
            )
        except Exception as exc:
            logger.warning(
                "Invoice VLM helper failed for %s: %s",
                build_model_spec(helper_target.provider, helper_target.model_id),
                exc,
            )
            return final_items, helper_target, "failed", 0, 0

        helper_items_count = len(helper_items)
        if not helper_items:
            return final_items, helper_target, "empty", 0, 0

        if not final_items:
            logger.info(
                "Invoice VLM helper rescued empty primary result with %s items via %s",
                helper_items_count,
                build_model_spec(helper_target.provider, helper_target.model_id),
            )
            return helper_items, helper_target, "rescue", 0, helper_items_count

        if not self._counts_are_close_enough_for_index_merge(len(final_items), helper_items_count):
            logger.info(
                "Invoice VLM helper skipped due to item-count mismatch via %s: primary_items=%s, helper_items=%s",
                build_model_spec(helper_target.provider, helper_target.model_id),
                len(final_items),
                helper_items_count,
            )
            return final_items, helper_target, "count_mismatch", 0, helper_items_count

        merged_items, helper_updates = self._merge_items_with_vlm_helper(final_items, helper_items)
        helper_mode = "enrich" if helper_updates else "noop"
        logger.info(
            "Invoice VLM helper %s via %s: helper_items=%s, updated_fields=%s",
            helper_mode,
            build_model_spec(helper_target.provider, helper_target.model_id),
            helper_items_count,
            helper_updates,
        )
        return merged_items, helper_target, helper_mode, helper_updates, helper_items_count

    def _resolve_vlm_helper_target(self, runtime):
        raw_spec = str(getattr(runtime, "invoice_vlm_helper_model", "") or "").strip()
        if raw_spec.lower() == "off":
            return None
        if raw_spec:
            try:
                target = resolve_model_target(raw_spec)
            except Exception as exc:
                logger.warning("Invalid INVOICE_VLM_HELPER_MODEL '%s': %s", raw_spec, exc)
                return None
            if target.provider != "vlm":
                logger.warning("INVOICE_VLM_HELPER_MODEL must point to a vlm:: model, got '%s'", raw_spec)
                return None
            return target

        vlm_base_url = str(getattr(runtime, "vlm_base_url", "") or "").strip()
        vlm_models = tuple(getattr(runtime, "vlm_models", ()) or ())
        if not vlm_base_url or not vlm_models:
            return None
        return resolve_model_target(build_model_spec("vlm", vlm_models[0]))

    def _merge_items_with_vlm_helper(self, primary_items, helper_items):
        merged_items = [dict(item) for item in primary_items]
        updates = 0

        for idx, helper_item in enumerate(helper_items):
            if idx >= len(merged_items):
                break
            updates += self._fill_missing_from_helper(merged_items[idx], helper_item)

        return merged_items, updates

    def _fill_missing_from_helper(self, primary_item, helper_item):
        fillable_fields = (
            "description",
            "quantity",
            "unit",
            "cost",
            "price",
            "hs_code",
            "currency_code",
            "currency_name",
            "document_date",
            "document_number",
            "country_origin",
            "country_origin_code",
            "country_sender",
        )
        updates = 0
        for field_name in fillable_fields:
            if self._is_empty_invoice_value(primary_item.get(field_name)) and not self._is_empty_invoice_value(helper_item.get(field_name)):
                primary_item[field_name] = helper_item.get(field_name)
                updates += 1
        return updates

    def _counts_are_close_enough_for_index_merge(self, primary_count: int, helper_count: int) -> bool:
        if primary_count <= 0 or helper_count <= 0:
            return False

        allowed_delta = max(5, primary_count // 5)
        return abs(primary_count - helper_count) <= allowed_delta

    def _is_empty_invoice_value(self, value):
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"", "none", "null", "-"}
        return False

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
            # Guarantee forward progress: newline-snapping can pull `end` close to
            # `start`, and a large overlap could otherwise move `start` backward,
            # causing an infinite loop. `max(start + 1, ...)` keeps it monotonic.
            start = max(start + 1, end - overlap) if end < len(text) else len(text)
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
