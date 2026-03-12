from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from fastapi_app.main import app


class FastAPISmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("fastapi_app.main.execute_extraction_request")
    def test_extract_returns_stateless_payload(self, mock_execute):
        mock_execute.return_value = {
            "status": "success",
            "document_code": "04021",
            "model_id": "gpt-oss-120b",
            "items": [{"position": 1, "description": "Item"}],
            "count": 1,
            "metrics": {"primary_valid": True},
            "error": "",
        }

        response = self.client.post(
            "/api/extract/",
            json={"document_code": "04021", "ocr_draft": "Invoice", "model": "cerebras"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["model_id"], "gpt-oss-120b")

    def test_extract_returns_400_for_unsupported_document_code(self):
        response = self.client.post(
            "/api/extract/",
            json={"document_code": "99999", "ocr_draft": "Invoice"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("only handles document_code", response.json()["detail"])
