import unittest
import os
import time
from unittest.mock import Mock, patch

from extractor.config.runtime import clear_runtime_settings_cache
from extractor.documents.base import DocumentDefinition, DocumentSchema
from extractor.services.extraction import execute_extraction_request


class ApiServiceTests(unittest.TestCase):
    def tearDown(self):
        clear_runtime_settings_cache()
        os.environ.pop("EXTRACTION_TIMEOUT_S", None)

    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_returns_flat_success_payload(self, mock_get_definition):
        mock_handler = Mock()
        mock_handler.result_type = "table"
        mock_handler.extract.return_value = {
            "data": {
                "fields": {"document_number": "INV-1"},
                "items": [{"position": 1, "description": "Item"}],
                "count": 1,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gpt-oss-120b",
        }
        mock_get_definition.return_value = DocumentDefinition(
            document_code="04021",
            label="Invoice",
            handler=mock_handler,
            schema=DocumentSchema(result_type="table"),
        )

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft="Invoice text",
            model="cerebras",
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["result_type"], "table")
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["document_schema"]["result_type"], "table")
        self.assertEqual(response["data"]["fields"]["document_number"], "INV-1")
        self.assertEqual(response["items"][0]["position"], 1)
        self.assertEqual(response["metrics"]["model_selection"]["mode"], "manual")
        self.assertEqual(response["metrics"]["model_selection"]["selected_model"], "cerebras")

    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_returns_flat_error_payload(self, mock_get_definition):
        mock_handler = Mock()
        mock_handler.result_type = "table"
        mock_handler.extract.return_value = {
            "error": "No valid items extracted",
            "data": {"fields": {}, "items": [], "count": 0},
            "metrics": {"primary_valid": False},
            "model_id": "gemini-2.5-flash",
        }
        mock_get_definition.return_value = DocumentDefinition(
            document_code="04021",
            label="Invoice",
            handler=mock_handler,
            schema=DocumentSchema(result_type="table"),
        )

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft="Invoice text",
            model="gemini",
        )

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["result_type"], "table")
        self.assertEqual(response["count"], 0)
        self.assertEqual(response["document_schema"]["result_type"], "table")
        self.assertEqual(response["model_id"], "gemini-2.5-flash")
        self.assertEqual(response["metrics"]["model_selection"]["mode"], "manual")

    @patch.dict(
        os.environ,
        {
            "MODEL_AUTO_ROUTE": "true",
            "MODEL_AUTO_ROUTE_SMALL_DOC": "gemini-flash",
            "MODEL_AUTO_ROUTE_LARGE_TABLE": "cerebras",
            "CEREBRAS_API_KEY": "csk_test_1234567890",
            "LANGEXTRACT_API_KEY": "AIzaSyGeminiTest123456",
        },
        clear=False,
    )
    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_auto_routes_large_table_to_cerebras(
        self,
        mock_get_definition,
    ):
        clear_runtime_settings_cache()
        mock_handler = Mock()
        mock_handler.result_type = "table"
        mock_handler.extract.return_value = {
            "data": {"fields": {}, "items": [], "count": 0},
            "metrics": {"primary_valid": True},
            "model_id": "gpt-oss-120b",
        }
        mock_get_definition.return_value = DocumentDefinition(
            document_code="04021",
            label="Invoice",
            handler=mock_handler,
            schema=DocumentSchema(result_type="table"),
        )

        large_ocr = "\n".join(
            [f"| {idx} | Item {idx} | 85181090 | 1 | 10.00 | 10.00 |" for idx in range(40)]
        )

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft=large_ocr,
            model=None,
        )

        mock_handler.extract.assert_called_once_with(ocr_draft=large_ocr, model="cerebras")
        self.assertEqual(response["metrics"]["model_selection"]["mode"], "auto")
        self.assertEqual(
            response["metrics"]["model_selection"]["reason"],
            "large_or_tabular_table_document",
        )
        self.assertEqual(response["metrics"]["model_selection"]["selected_model"], "cerebras")

    @patch.dict(
        os.environ,
        {
            "MODEL_AUTO_ROUTE": "true",
            "MODEL_AUTO_ROUTE_OBJECT_DEFAULT": "gemini-flash",
            "LANGEXTRACT_API_KEY": "AIzaSyGeminiTest123456",
        },
        clear=False,
    )
    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_auto_routes_object_doc_to_gemini(
        self,
        mock_get_definition,
    ):
        clear_runtime_settings_cache()
        mock_handler = Mock()
        mock_handler.result_type = "object"
        mock_handler.extract.return_value = {
            "data": {"fields": {"document_number": "A-1"}, "items": [], "count": 0},
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }
        mock_get_definition.return_value = DocumentDefinition(
            document_code="03011",
            label="Contract",
            handler=mock_handler,
            schema=DocumentSchema(result_type="object"),
        )

        response = execute_extraction_request(
            document_code="03011",
            ocr_draft="Contract No. A-1",
            model=None,
        )

        mock_handler.extract.assert_called_once_with(
            ocr_draft="Contract No. A-1",
            model="gemini-flash",
        )
        self.assertEqual(response["metrics"]["model_selection"]["mode"], "auto")
        self.assertEqual(response["metrics"]["model_selection"]["reason"], "object_document")
        self.assertEqual(
            response["metrics"]["model_selection"]["selected_model"],
            "gemini-flash",
        )

    @patch.dict(os.environ, {"EXTRACTION_TIMEOUT_S": "0.01"}, clear=False)
    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_times_out_stuck_handler(self, mock_get_definition):
        clear_runtime_settings_cache()
        mock_handler = Mock()
        mock_handler.result_type = "table"
        mock_handler.extract_timeout_fallback = None

        def slow_extract(*, ocr_draft, model):
            time.sleep(0.05)
            return {
                "data": {"fields": {}, "items": [], "count": 0},
                "metrics": {"primary_valid": True},
                "model_id": model,
            }

        mock_handler.extract.side_effect = slow_extract
        mock_get_definition.return_value = DocumentDefinition(
            document_code="04021",
            label="Invoice",
            handler=mock_handler,
            schema=DocumentSchema(result_type="table"),
        )

        with self.assertRaises(TimeoutError) as exc:
            execute_extraction_request(
                document_code="04021",
                ocr_draft="Invoice text",
                model="cerebras",
            )

        self.assertIn("timed out", str(exc.exception).lower())

    @patch.dict(os.environ, {"EXTRACTION_TIMEOUT_S": "0.01"}, clear=False)
    @patch("extractor.services.extraction.get_document_definition")
    def test_execute_extraction_request_uses_timeout_fallback_when_handler_supports_it(
        self,
        mock_get_definition,
    ):
        clear_runtime_settings_cache()

        class TimeoutCapableHandler:
            result_type = "table"

            def extract(self, *, ocr_draft, model):
                time.sleep(0.05)
                return {
                    "data": {"fields": {}, "items": [], "count": 0},
                    "metrics": {"primary_valid": True},
                    "model_id": model,
                }

            def extract_timeout_fallback(self, *, ocr_draft, model=None, error=None):
                return {
                    "data": {"fields": {"document_number": "INV-1"}, "items": [{"position": 1}], "count": 1},
                    "metrics": {"execution_path": {"mode": "parser_timeout_fallback"}},
                    "model_id": "structured-parser",
                    "result_type": "table",
                }

        mock_get_definition.return_value = DocumentDefinition(
            document_code="04021",
            label="Invoice",
            handler=TimeoutCapableHandler(),
            schema=DocumentSchema(result_type="table"),
        )

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft="Invoice text",
            model="cerebras",
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["model_id"], "structured-parser")
        self.assertEqual(response["count"], 1)
