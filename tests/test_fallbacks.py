from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extractor.invoice.invoice import InvoiceHandler
from extractor.invoice.invoice_utils import validate_and_format_invoice
from extractor.providers import ModelTarget


class _FakeProvider:
    def __init__(self, responses, *, supports_large_context=True):
        self._responses = list(responses)
        self.supports_large_context = supports_large_context

    def generate(self, *args, **kwargs):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeVLMProvider(_FakeProvider):
    def generate_from_images(self, *args, **kwargs):
        return self.generate(*args, **kwargs)


class FallbackTests(unittest.TestCase):
    def test_invoice_chunking_uses_per_chunk_fallback_without_switching_final_model(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        providers = {
            "gemini": _FakeProvider(['{"items": []}']),
            "openai": _FakeProvider(['{"items": [{"description": "Bolt", "quantity": 1}]}']),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
        ):
            result = InvoiceHandler().extract(ocr_draft="text", model="gemini::gemini-1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["items"][0]["description"], "Bolt")
        self.assertEqual(result["model_id"], "gemini::gemini-1")
        self.assertFalse(result["metrics"]["execution"]["fallback_used"])

    def test_invoice_vllm_chunking_uses_vllm_chunk_settings(self) -> None:
        primary_target = ModelTarget(provider="vllm", model_id="Qwen/Qwen2.5-14B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vllm": _FakeProvider([], supports_large_context=False),
            "gemini": _FakeProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="gemini::gemini-2.5-flash-lite",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_chunked_workflow",
                side_effect=[
                    {"items": []},
                ],
            ) as run_chunked,
        ):
            result = InvoiceHandler().extract(ocr_draft="text", model="vllm::Qwen/Qwen2.5-14B-Instruct")

        self.assertEqual(run_chunked.call_count, 1)
        _, _, _, _, _, max_c, max_workers = run_chunked.call_args.args
        self.assertEqual(max_c, 20000)
        self.assertEqual(max_workers, 2)
        self.assertEqual(result["status"], "success")

    def test_invoice_vlm_requires_source_file_path(self) -> None:
        primary_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen2.5-VL-7B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vlm": _FakeVLMProvider([]),
            "gemini": _FakeProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="gemini::gemini-2.5-flash-lite",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
        ):
            result = InvoiceHandler().extract(ocr_draft="", model="vlm::Qwen/Qwen2.5-VL-7B-Instruct")

        self.assertEqual(result["status"], "failed")
        self.assertIn("source_file_path", result["error"])

    def test_invoice_vlm_uses_visual_workflow(self) -> None:
        primary_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen2.5-VL-7B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vlm": _FakeVLMProvider(['{"items": [{"description": "Bolt", "quantity": 1}]}']),
            "gemini": _FakeProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="gemini::gemini-2.5-flash-lite",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch(
                "extractor.invoice.invoice.build_visual_inputs",
                return_value=["data:image/png;base64,abc"],
            ) as build_visual_inputs,
        ):
            result = InvoiceHandler().extract(
                ocr_draft="",
                model="vlm::Qwen/Qwen2.5-VL-7B-Instruct",
                source_file_path="/tmp/invoice.pdf",
            )

        build_visual_inputs.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["model_id"], "vlm::Qwen/Qwen2.5-VL-7B-Instruct")

    def test_invoice_vlm_helper_enriches_primary_items_without_switching_final_model(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        helper_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen3-VL-8B-Instruct")
        providers = {
            "gemini": _FakeProvider([]),
            "openai": _FakeProvider([]),
            "vlm": _FakeVLMProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target, helper_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_base_url="http://vlm.local/v1",
                    vlm_models=("Qwen/Qwen3-VL-8B-Instruct",),
                    invoice_vlm_helper_model="vlm::Qwen/Qwen3-VL-8B-Instruct",
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_chunked_workflow",
                return_value={"items": [{"description": "Bolt", "quantity": 1, "hs_code": None}]},
            ),
            patch.object(
                InvoiceHandler,
                "_run_vlm_workflow",
                return_value=[{"description": "Bolt", "quantity": 1, "hs_code": "8471490000"}],
            ),
        ):
            result = InvoiceHandler().extract(
                ocr_draft="text",
                model="gemini::gemini-1",
                source_file_path="/tmp/invoice.pdf",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["model_id"], "gemini::gemini-1")
        self.assertEqual(result["data"]["items"][0]["hs_code"], "8471490000")
        self.assertEqual(
            result["metrics"]["execution"]["vlm_helper_model"],
            "vlm::Qwen/Qwen3-VL-8B-Instruct",
        )
        self.assertEqual(result["metrics"]["execution"]["vlm_helper_mode"], "enrich")

    def test_invoice_vlm_helper_can_rescue_empty_primary_result(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        helper_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen3-VL-8B-Instruct")
        providers = {
            "gemini": _FakeProvider([]),
            "openai": _FakeProvider([]),
            "vlm": _FakeVLMProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target, helper_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_base_url="http://vlm.local/v1",
                    vlm_models=("Qwen/Qwen3-VL-8B-Instruct",),
                    invoice_vlm_helper_model="vlm::Qwen/Qwen3-VL-8B-Instruct",
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_chunked_workflow",
                return_value={"items": []},
            ),
            patch.object(
                InvoiceHandler,
                "_run_vlm_workflow",
                return_value=[{"description": "Bolt", "quantity": 1}],
            ),
        ):
            result = InvoiceHandler().extract(
                ocr_draft="text",
                model="gemini::gemini-1",
                source_file_path="/tmp/invoice.pdf",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["model_id"], "vlm::Qwen/Qwen3-VL-8B-Instruct")
        self.assertEqual(result["metrics"]["execution"]["vlm_helper_mode"], "rescue")

    def test_invoice_vlm_helper_skips_index_merge_when_counts_mismatch(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        helper_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen3-VL-8B-Instruct")
        providers = {
            "gemini": _FakeProvider([]),
            "openai": _FakeProvider([]),
            "vlm": _FakeVLMProvider([]),
        }

        primary_items = [{"description": f"Item {idx}", "quantity": 1} for idx in range(10)]
        helper_items = [{"description": f"Helper {idx}", "quantity": 1, "hs_code": f"847149{idx:04d}"} for idx in range(30)]

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target, helper_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_base_url="http://vlm.local/v1",
                    vlm_models=("Qwen/Qwen3-VL-8B-Instruct",),
                    invoice_vlm_helper_model="vlm::Qwen/Qwen3-VL-8B-Instruct",
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_chunked_workflow",
                return_value={"items": primary_items},
            ),
            patch.object(
                InvoiceHandler,
                "_run_vlm_workflow",
                return_value=helper_items,
            ),
        ):
            result = InvoiceHandler().extract(
                ocr_draft="text",
                model="gemini::gemini-1",
                source_file_path="/tmp/invoice.pdf",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 10)
        self.assertEqual(result["data"]["items"][0]["description"], "Item 0")
        self.assertEqual(result["metrics"]["execution"]["vlm_helper_mode"], "count_mismatch")
        self.assertEqual(result["metrics"]["execution"]["vlm_helper_updates"], 0)

    def test_invoice_scan_table_helper_can_rescue_empty_primary_result(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        providers = {
            "gemini": _FakeProvider([]),
            "openai": _FakeProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_base_url="",
                    vlm_models=(),
                    invoice_vlm_helper_model="",
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_chunked_workflow",
                return_value={"items": []},
            ),
            patch(
                "extractor.invoice.invoice.extract_scan_table_invoice",
                return_value={
                    "items": [
                        {"description": "Widget A", "quantity": 1, "hs_code": "8471490000"},
                        {"description": "Widget B", "quantity": 2, "hs_code": "8471490001"},
                    ],
                    "count": 2,
                    "looks_like_scan_table": True,
                },
            ),
        ):
            result = InvoiceHandler().extract(
                ocr_draft="1 Widget A\n2 Widget B",
                model="gemini::gemini-1",
                source_file_path="/tmp/invoice.pdf",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 2)
        self.assertEqual(result["model_id"], "gemini::gemini-1")
        self.assertEqual(result["metrics"]["execution"]["scan_helper_mode"], "rescue")

    def test_invoice_scan_table_helper_can_override_vlm_primary_with_ocr(self) -> None:
        primary_target = ModelTarget(provider="vlm", model_id="Qwen/Qwen3-VL-8B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vlm": _FakeVLMProvider([]),
            "gemini": _FakeProvider([]),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="gemini::gemini-2.5-flash-lite",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                    vlm_pdf_render_dpi=144,
                    vlm_pages_per_prompt=1,
                    vlm_max_pages=12,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                InvoiceHandler,
                "_run_vlm_workflow",
                return_value=[{"description": "Widget A", "quantity": 1}],
            ),
            patch(
                "extractor.invoice.invoice.extract_scan_table_invoice",
                return_value={
                    "items": [
                        {"description": "Widget A", "quantity": 1},
                        {"description": "Widget B", "quantity": 2},
                        {"description": "Widget C", "quantity": 3},
                        {"description": "Widget D", "quantity": 4},
                        {"description": "Widget E", "quantity": 5},
                    ],
                    "count": 5,
                    "looks_like_scan_table": True,
                },
            ),
        ):
            result = InvoiceHandler().extract(
                ocr_draft="1 Widget A\n2 Widget B\n3 Widget C\n4 Widget D\n5 Widget E",
                model="vlm::Qwen/Qwen3-VL-8B-Instruct",
                source_file_path="/tmp/invoice.pdf",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 5)
        self.assertEqual(result["model_id"], "vlm::Qwen/Qwen3-VL-8B-Instruct")
        self.assertEqual(result["metrics"]["execution"]["scan_helper_mode"], "override")

    def test_invoice_chunking_keeps_primary_model_label_even_when_chunk_fallback_is_used(self) -> None:
        primary_target = ModelTarget(provider="vllm", model_id="Qwen/Qwen2.5-14B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vllm": _FakeProvider(['{"items": []}'], supports_large_context=False),
            "gemini": _FakeProvider(['{"items": [{"description": "Bolt", "quantity": 1}]}']),
        }

        with (
            patch("extractor.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.invoice.invoice.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="gemini::gemini-2.5-flash-lite",
                    invoice_chunk_size_gemini=100000,
                    invoice_chunk_size_openai=80000,
                    invoice_chunk_size_ollama=20000,
                    invoice_chunk_size_cerebras=3500,
                    invoice_chunk_size_vllm=20000,
                    invoice_vllm_max_workers=2,
                    invoice_chunk_overlap_default=600,
                    invoice_chunk_overlap_vllm=100,
                    chunk_size_default=100000,
                ),
            ),
            patch("extractor.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
        ):
            result = InvoiceHandler().extract(ocr_draft="text", model="vllm::Qwen/Qwen2.5-14B-Instruct")

        self.assertEqual(result["model_id"], "vllm::Qwen/Qwen2.5-14B-Instruct")
        self.assertFalse(result["metrics"]["execution"]["fallback_used"])
        self.assertEqual(result["data"]["count"], 1)

    def test_invoice_dedup_keeps_same_price_rows_with_different_descriptions(self) -> None:
        handler = InvoiceHandler()
        rows = [
            {"description": "Screw nipple", "quantity": 4, "unit": "pcs", "price": 4.66, "cost": 18.64, "hs_code": "A"},
            {"description": "Nut", "quantity": 4, "unit": "pcs", "price": 4.66, "cost": 18.64, "hs_code": "B"},
        ]

        deduped = handler._dedupe_invoice_rows(rows)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["description"], "Screw nipple")
        self.assertEqual(deduped[1]["description"], "Nut")

    def test_invoice_dedup_removes_nearby_exact_duplicate_rows(self) -> None:
        handler = InvoiceHandler()
        row = {"description": "Screw nipple", "quantity": 4, "unit": "pcs", "price": 4.66, "cost": 18.64, "hs_code": "A"}
        rows = [
            row,
            {"description": "Nut", "quantity": 10, "unit": "pcs", "price": 1.33, "cost": 13.3, "hs_code": "B"},
            dict(row),
        ]

        deduped = handler._dedupe_invoice_rows(rows)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["description"], "Screw nipple")
        self.assertEqual(deduped[1]["description"], "Nut")

    def test_invoice_chunk_split_uses_overlap_strategy(self) -> None:
        handler = InvoiceHandler()
        text = "A" * 1800

        chunks = handler._split_invoice_chunks(text, 1000)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0], text[:1000])
        self.assertEqual(chunks[1], text[400:1400])

    def test_invoice_vllm_overlap_is_reduced(self) -> None:
        handler = InvoiceHandler()
        runtime = SimpleNamespace(invoice_chunk_overlap_default=600, invoice_chunk_overlap_vllm=100)

        overlap = handler._chunk_overlap_for_provider(runtime, "vllm", 1000)

        self.assertEqual(overlap, 100)

    def test_invoice_validation_marks_long_non_json_as_invalid(self) -> None:
        is_valid, reason, items = validate_and_format_invoice("not json " * 40)

        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
        self.assertEqual(items, [])

    def test_invoice_validation_treats_truncated_json_as_empty(self) -> None:
        is_valid, reason, items = validate_and_format_invoice('{"items":[{"description":"Bolt"}')

        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
        self.assertEqual(items, [])

    def test_invoice_validation_reports_empty_items_reason(self) -> None:
        is_valid, reason, items = validate_and_format_invoice('{"items": []}')

        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
