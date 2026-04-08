from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extractor.documents.base import DocumentFieldSchema, DocumentSchema
from extractor.documents.invoice.invoice import InvoiceHandler
from extractor.documents.invoice.invoice_utils import validate_and_format_invoice
from extractor.documents.object_core import BaseObjectHandler
from extractor.documents.regular.technical_document import TechnicalDocumentHandler
from extractor.integrations.providers import ModelTarget


class _FakeProvider:
    def __init__(self, responses, *, supports_large_context=True):
        self._responses = list(responses)
        self.supports_large_context = supports_large_context

    def generate(self, *args, **kwargs):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _DummyObjectHandler(BaseObjectHandler):
    document_code = "TEST"
    label = "Dummy"
    schema = DocumentSchema(
        result_type="object",
        fields=(DocumentFieldSchema("document_number", "Document Number"),),
    )
    empty_error = "No dummy fields extracted"


class FallbackTests(unittest.TestCase):
    def test_object_handler_uses_fallback_after_parse_failure(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        providers = {
            "gemini": _FakeProvider(["not a json payload"]),
            "openai": _FakeProvider(['{"document_number": "DOC-42"}']),
        }

        with (
            patch("extractor.documents.object_core.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch("extractor.documents.object_core.get_runtime_settings", return_value=SimpleNamespace(llm_model_fallback="openai::gpt-4o-mini")),
            patch("extractor.documents.object_core.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
        ):
            result = _DummyObjectHandler().extract(ocr_draft="text", model="gemini::gemini-1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["fields"]["document_number"], "DOC-42")
        self.assertEqual(result["model_id"], "openai::gpt-4o-mini")
        self.assertTrue(result["metrics"]["execution"]["fallback_used"])

    def test_invoice_chunking_uses_per_chunk_fallback_without_switching_final_model(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        providers = {
            "gemini": _FakeProvider(['{"items": []}']),
            "openai": _FakeProvider(['{"items": [{"description": "Bolt", "quantity": 1}]}']),
        }

        with (
            patch("extractor.documents.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.documents.invoice.invoice.get_runtime_settings",
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
            patch("extractor.documents.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
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
            patch("extractor.documents.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.documents.invoice.invoice.get_runtime_settings",
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
            patch("extractor.documents.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
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

    def test_technical_document_always_uses_default_chunking(self) -> None:
        primary_target = ModelTarget(provider="gemini", model_id="gemini-1")
        fallback_target = ModelTarget(provider="openai", model_id="gpt-4o-mini")
        providers = {
            "gemini": _FakeProvider(['{"items": []}']),
            "openai": _FakeProvider(['{"items": []}']),
        }

        with (
            patch("extractor.documents.regular.technical_document.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.documents.regular.technical_document.get_runtime_settings",
                return_value=SimpleNamespace(
                    llm_model_fallback="openai::gpt-4o-mini",
                    chunk_size_default=12345,
                    default_chunk_max_workers=2,
                ),
            ),
            patch("extractor.documents.regular.technical_document.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
            patch.object(
                TechnicalDocumentHandler,
                "_run_chunked_workflow",
                return_value=({"items": []}, True),
            ) as run_chunked,
        ):
            result = TechnicalDocumentHandler().extract(ocr_draft="text", model="gemini::gemini-1")

        run_chunked.assert_called_once()
        _, _, _, max_c, max_workers = run_chunked.call_args.args
        self.assertEqual(max_c, 12345)
        self.assertEqual(max_workers, 2)
        self.assertEqual(result["status"], "success")

    def test_invoice_chunking_keeps_primary_model_label_even_when_chunk_fallback_is_used(self) -> None:
        primary_target = ModelTarget(provider="vllm", model_id="Qwen/Qwen2.5-14B-Instruct")
        fallback_target = ModelTarget(provider="gemini", model_id="gemini-2.5-flash-lite")
        providers = {
            "vllm": _FakeProvider(['{"items": []}'], supports_large_context=False),
            "gemini": _FakeProvider(['{"items": [{"description": "Bolt", "quantity": 1}]}']),
        }

        with (
            patch("extractor.documents.invoice.invoice.resolve_model_target", side_effect=[primary_target, fallback_target]),
            patch(
                "extractor.documents.invoice.invoice.get_runtime_settings",
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
            patch("extractor.documents.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
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
