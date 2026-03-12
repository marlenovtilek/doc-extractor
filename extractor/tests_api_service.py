from unittest.mock import patch
import unittest

from extractor.api_service import execute_extraction_request


class ApiServiceTests(unittest.TestCase):
    @patch("extractor.api_service.run_invoice_extraction")
    def test_execute_extraction_request_returns_flat_success_payload(self, mock_run):
        mock_run.return_value = {
            "result": {"items": [{"position": 1, "description": "Item"}], "count": 1},
            "metrics": {"primary_valid": True},
            "model_id": "gpt-oss-120b",
        }

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft="Invoice text",
            model="cerebras",
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["items"][0]["position"], 1)

    @patch("extractor.api_service.run_invoice_extraction")
    def test_execute_extraction_request_returns_flat_error_payload(self, mock_run):
        mock_run.return_value = {
            "error": "No valid items extracted",
            "metrics": {"primary_valid": False},
            "model_id": "gemini-2.5-flash",
        }

        response = execute_extraction_request(
            document_code="04021",
            ocr_draft="Invoice text",
            model="gemini",
        )

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["count"], 0)
        self.assertEqual(response["model_id"], "gemini-2.5-flash")
