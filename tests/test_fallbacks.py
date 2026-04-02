from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extractor.documents.base import DocumentFieldSchema, DocumentSchema
from extractor.documents.invoice.invoice import InvoiceHandler
from extractor.documents.object_core import BaseObjectHandler
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

    def test_invoice_single_pass_uses_fallback_after_empty_primary_items(self) -> None:
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
                    chunk_size_cerebras=3500,
                    chunk_size_default=100000,
                ),
            ),
            patch("extractor.documents.invoice.invoice.get_llm_provider", side_effect=lambda provider_name: providers[provider_name]),
        ):
            result = InvoiceHandler().extract(ocr_draft="text", model="gemini::gemini-1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["items"][0]["description"], "Bolt")
        self.assertEqual(result["model_id"], "openai::gpt-4o-mini")
        self.assertTrue(result["metrics"]["execution"]["fallback_used"])


if __name__ == "__main__":
    unittest.main()
