import unittest
from unittest.mock import Mock, patch

from extractor.api_service import execute_extraction_request
from extractor.documents.base import DocumentDefinition, DocumentSchema


class ApiServiceTests(unittest.TestCase):
    @patch("extractor.api_service.get_document_definition")
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

    @patch("extractor.api_service.get_document_definition")
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
