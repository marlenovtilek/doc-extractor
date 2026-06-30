import time
import re
import json
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

        # Universal validation (stated total vs sum, row count vs max POS) —
        # computed before we strip the helper fields it relies on.
        validation = self._build_invoice_validation(final_items)
        if validation["review_needed"]:
            logger.warning(
                "Invoice validation flags review: %s (count=%s, sum=%s, stated_total=%s)",
                validation["review_reasons"], validation["count"],
                validation["sum_cost"], validation["stated_total"],
            )
        if validation["warnings"]:
            logger.warning(
                "Invoice validation warnings: %s (ratio=%s, row_anomalies=%s)",
                validation["warnings"], validation["sum_to_total_ratio"],
                validation["row_anomaly_count"],
            )

        # Очистка и нумерация
        for i, item in enumerate(final_items, 1):
            item["position"] = i
            d = str(item.get("description", ""))
            item["description"] = re.sub(r'<[^>]*>', ' ', d).strip(" .,").strip()
            item.pop("document_number", None)
            item.pop("document_date", None)
            item.pop("country_sender", None)
            item.pop("line_no", None)
            item.pop("invoice_total_amount", None)

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
                },
                "validation": validation,
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
        passes = max(1, getattr(runtime, "vlm_passes", 1))
        all_raw: list[dict[str, Any]] = []
        page_totals: list[float] = []

        def run_pass() -> list[dict[str, Any]]:
            pass_items: list[dict[str, Any]] = []
            for start in range(0, len(visual_inputs), pages_per_prompt):
                page_batch = visual_inputs[start:start + pages_per_prompt]
                raw = provider.generate_from_images(
                    INVOICE_VLM_SYSTEM_PROMPT,
                    INVOICE_VLM_USER_PROMPT,
                    page_batch,
                    target.model_id,
                )
                # The invoice grand total lives on a summary page that usually has no
                # product rows, so capture it from the top-level JSON, not from items.
                total = self._extract_stated_total_from_raw(raw)
                if total is not None:
                    page_totals.append(total)
                valid, _, items = validate_and_format_invoice(raw)
                if valid and items:
                    pass_items.extend(items)
            return pass_items

        # First pass always runs. VLM under-reads rows on dense pages non-
        # deterministically, so additional passes recover different missed rows
        # and the POS-based union below merges them back into one set.
        first_pass = run_pass()
        all_raw.extend(first_pass)

        # Multi-pass union is only safe when the invoice has reliable printed row
        # numbers (POS): without them we cannot tell a recovered row from a
        # duplicate, so extra passes would inflate the count instead. And it is
        # only WORTH doing when the first pass looks incomplete — if its sum already
        # matches the invoice's stated total, extra passes only waste time.
        did_multipass = False
        if passes > 1 and self._line_numbering_reliable(first_pass):
            if self._vlm_first_pass_complete(first_pass, page_totals):
                logger.info("Invoice VLM first pass looks complete (sum≈total); skipping %s extra pass(es).", passes - 1)
            else:
                did_multipass = True
                for _ in range(passes - 1):
                    all_raw.extend(run_pass())

        # For visual extraction we prefer recall over aggressive duplicate
        # suppression. Page-by-page VLM runs were dropping too many real rows
        # when multiple items shared similar description/price patterns.
        #
        # Document-level duplication (same invoice present twice: a translated
        # copy + the original) AND multi-pass copies are both collapsed here by
        # the invoice's own printed row numbers — see _collapse_vlm_duplicates.
        collapsed = self._collapse_vlm_duplicates(all_raw, dedup_unnumbered=did_multipass)

        # Broadcast the invoice's stated grand total onto every row so the
        # validation layer can anchor the sum check on it.
        stated_total = self._choose_stated_total(page_totals)
        if stated_total is not None:
            for item in collapsed:
                item["invoice_total_amount"] = stated_total
        return collapsed

    def _extract_stated_total_from_raw(self, raw: str) -> float | None:
        if not raw:
            return None
        try:
            match = re.search(r"\{.*\}", str(raw), re.DOTALL)
            if not match:
                return None
            obj = json.loads(match.group(0))
        except Exception:
            return None
        if isinstance(obj, dict):
            return self._parse_invoice_decimal(obj.get("invoice_total_amount"))
        return None

    def _vlm_first_pass_complete(self, items: list[dict[str, Any]], page_totals: list[float]) -> bool:
        """True when the first VLM pass already accounts for the whole invoice — its
        line-item sum reaches the stated grand total. Used to skip extra passes on
        clean invoices. If there is no readable total we cannot confirm completeness,
        so we return False and let the safety pass run."""
        if not items:
            return False
        item_sum = sum(self._parse_invoice_decimal(it.get("cost")) or 0 for it in items)
        stated_total = self._choose_stated_total(page_totals)
        if not stated_total or stated_total <= 0:
            return False
        return (item_sum / stated_total) >= 0.97

    def _choose_stated_total(self, totals: list[float]) -> float | None:
        # The grand total is, by definition, the LARGEST total on the invoice:
        # carry-overs / page subtotals / "Übertrag" lines are always smaller than
        # the final total. Picking the max is the safe choice — if a stray large
        # value slips in it only over-flags (sum_below), whereas picking a smaller
        # subtotal would mask an under-read extraction as "clean" (the 014 trap).
        valid = [round(t, 2) for t in totals if t and t > 0]
        return max(valid) if valid else None

    @staticmethod
    def _parse_invoice_decimal(value: Any) -> float | None:
        if value is None:
            return None
        s = re.sub(r"[^0-9,.\-]", "", str(value))
        if not s or s in {"-", ".", ","}:
            return None
        if "," in s and "." in s:
            # Last separator is the decimal one; the other groups thousands.
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def _parse_line_no(value: Any) -> int | None:
        if value is None:
            return None
        m = re.search(r"\d+", str(value))
        return int(m.group(0)) if m else None

    def _vlm_item_completeness(self, item: dict[str, Any]) -> int:
        keys = ("description", "quantity", "price", "cost", "hs_code", "country_origin", "country_origin_code")
        return sum(1 for k in keys if not self._is_empty_invoice_value(item.get(k)))

    def _line_numbering_reliable(self, items: list[dict[str, Any]]) -> bool:
        """True when enough rows carry a printed POS number to safely union/collapse
        copies by that number (multi-pass recovery, doubled-document dedup)."""
        if not items:
            return False
        with_no = sum(1 for it in items if self._parse_line_no(it.get("line_no")) is not None)
        return (with_no / len(items)) >= 0.6

    def _is_row_arithmetic_consistent(self, item: dict[str, Any]) -> bool:
        """A real row's total equals quantity × unit price. Dense translated copies
        often misread the numeric columns (e.g. unit price lands in the total cell),
        breaking this identity — so it tells us which copy has the trustworthy numbers."""
        q = self._parse_invoice_decimal(item.get("quantity"))
        p = self._parse_invoice_decimal(item.get("price"))
        c = self._parse_invoice_decimal(item.get("cost"))
        if not q or p is None or not c or c <= 0:
            return False
        return abs(q * p - c) / c <= 0.02

    def _merge_line_group(self, group: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge all copies of one invoice row (same POS seen in translation + original)
        into a single row: numbers from the arithmetically consistent copy, and HS code /
        country / unit filled in from whichever copy carries them."""
        if len(group) == 1:
            return group[0]

        # Base = the copy with trustworthy numbers (cost == qty*price), then most complete.
        base = max(group, key=lambda it: (self._is_row_arithmetic_consistent(it), self._vlm_item_completeness(it)))
        merged = dict(base)
        fill_fields = (
            "hs_code", "unit", "country_origin", "country_origin_code",
            "description", "currency_code", "currency_name", "invoice_total_amount",
        )
        for other in group:
            if other is base:
                continue
            for field_name in fill_fields:
                if self._is_empty_invoice_value(merged.get(field_name)) and not self._is_empty_invoice_value(other.get(field_name)):
                    merged[field_name] = other.get(field_name)
        return merged

    def _collapse_vlm_duplicates(self, items: list[dict[str, Any]], dedup_unnumbered: bool = False) -> list[dict[str, Any]]:
        """Collapse a doubled invoice (translation + original in one PDF) into one
        copy using the invoice's OWN printed row numbers (POS/№). A repeated row
        number means the same logical row seen in a second representation, so we
        keep the single most complete version. Universal: with a single copy no
        number repeats and the list is returned untouched.

        dedup_unnumbered: set when the input accumulates several VLM passes — rows
        that carry no POS number would otherwise be duplicated once per pass, so we
        drop exact content duplicates among them."""
        if not items:
            return items

        if not self._line_numbering_reliable(items):
            # Row numbering is missing/unreliable — don't risk dropping real rows.
            return items

        parsed = [(self._parse_line_no(it.get("line_no")), it) for it in items]

        groups: dict[int, list[dict[str, Any]]] = {}
        order: list[int] = []
        no_number: list[dict[str, Any]] = []
        for ln, it in parsed:
            if ln is None:
                no_number.append(it)
                continue
            if ln not in groups:
                groups[ln] = []
                order.append(ln)
            groups[ln].append(it)

        if not any(len(v) > 1 for v in groups.values()) and not dedup_unnumbered:
            return items  # single representation — nothing to collapse

        if dedup_unnumbered and no_number:
            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for it in no_number:
                fp = self._invoice_item_fingerprint(it)
                if fp in seen:
                    continue
                seen.add(fp)
                deduped.append(it)
            no_number = deduped

        collapsed = [self._merge_line_group(groups[ln]) for ln in sorted(groups)]
        collapsed.extend(no_number)  # never silently drop rows without a number
        logger.info(
            "Invoice VLM duplicate-collapse: raw=%s -> %s (unique line_no=%s, unnumbered kept=%s)",
            len(items), len(collapsed), len(groups), len(no_number),
        )
        return collapsed

    def _build_invoice_validation(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Universal sanity check anchored on the invoice's own stated grand total
        and printed row count — flags likely under/over-extraction for human review."""
        from collections import Counter

        totals: Counter = Counter()
        for it in items:
            t = self._parse_invoice_decimal(it.get("invoice_total_amount"))
            if t:
                totals[round(t, 2)] += 1
        stated_total = totals.most_common(1)[0][0] if totals else None

        sum_cost = round(sum(self._parse_invoice_decimal(it.get("cost")) or 0 for it in items), 2)
        line_nos = [self._parse_line_no(it.get("line_no")) for it in items]
        line_nos = [x for x in line_nos if x is not None]
        max_line_no = max(line_nos) if line_nos else None
        count = len(items)

        # Per-row arithmetic check: a real row's total equals quantity × unit price.
        # Pinpoints the exact suspect rows (e.g. a single mis-read 45-million cell)
        # so an inspector reviews one line, not the whole invoice.
        row_anomalies: list[dict[str, Any]] = []
        for idx, it in enumerate(items, 1):
            q = self._parse_invoice_decimal(it.get("quantity"))
            p = self._parse_invoice_decimal(it.get("price"))
            c = self._parse_invoice_decimal(it.get("cost"))
            if q and p is not None and c and c > 0 and abs(q * p - c) / c > 0.02:
                row_anomalies.append({
                    "position": idx,
                    "quantity": it.get("quantity"),
                    "price": it.get("price"),
                    "cost": it.get("cost"),
                    "expected_cost": round(q * p, 2),
                })

        reasons: list[str] = []   # hard flags — extraction is likely broken
        warnings: list[str] = []  # soft flags — worth a human glance
        ratio = None
        if stated_total and stated_total > 0:
            ratio = round(sum_cost / stated_total, 3)
            if ratio > 1.10:
                reasons.append("sum_exceeds_total")
            elif ratio < 0.90:
                reasons.append("sum_below_total")
            elif abs(ratio - 1) > 0.02:
                warnings.append("sum_off_total_minor")
        if max_line_no and count and abs(max_line_no - count) > max(2, int(count * 0.05)):
            reasons.append("count_vs_max_line_mismatch")
        if row_anomalies:
            warnings.append("row_arithmetic_anomalies")

        return {
            "stated_total": stated_total,
            "sum_cost": sum_cost,
            "count": count,
            "max_line_no": max_line_no,
            "sum_to_total_ratio": ratio,
            "review_needed": bool(reasons),
            "review_reasons": reasons,
            "warnings": warnings,
            "row_anomaly_count": len(row_anomalies),
            "row_anomalies": row_anomalies[:20],
        }

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
