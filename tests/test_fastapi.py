import os
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from app.main import app
from extractor.runtime import clear_runtime_settings_cache


class FastAPISmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self._original_api_token = os.environ.get("DOC_EXTRACTOR_API_TOKEN")
        os.environ.pop("DOC_EXTRACTOR_API_TOKEN", None)
        clear_runtime_settings_cache()

    def tearDown(self):
        if self._original_api_token is None:
            os.environ.pop("DOC_EXTRACTOR_API_TOKEN", None)
        else:
            os.environ["DOC_EXTRACTOR_API_TOKEN"] = self._original_api_token
        clear_runtime_settings_cache()

    def test_home_page_renders_ui(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("doc-extractor", response.text)
        self.assertIn("Run Extraction", response.text)
        self.assertIn("Model Connections", response.text)
        self.assertIn("API Docs", response.text)
        self.assertIn("error-banner", response.text)

    def test_favicon_returns_no_content(self):
        response = self.client.get("/favicon.ico")

        self.assertEqual(response.status_code, 204)

    def test_swagger_docs_are_available(self):
        response = self.client.get("/docs")

        self.assertEqual(response.status_code, 200)

    def test_meta_returns_documents_and_models(self):
        response = self.client.get("/api/meta/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        documents = {item["document_code"]: item for item in payload["documents"]}
        self.assertEqual(documents["04021"]["label"], "Invoice")
        self.assertEqual(documents["04021"]["schema"]["result_type"], "table")
        self.assertEqual(documents["03011"]["label"], "Contract")
        self.assertEqual(documents["03011"]["schema"]["result_type"], "object")
        self.assertEqual(documents["00012"]["label"], "Supply Contract")
        self.assertEqual(documents["11019"]["label"], "Power of Attorney")
        self.assertEqual(documents["09022"]["label"], "Technical Document")
        self.assertEqual(documents["09022"]["schema"]["result_type"], "table")
        self.assertIn("models", payload)
        self.assertIn("model_families", payload)
        self.assertIn("providers", payload)
        self.assertIn("defaults", payload)
        self.assertIn("configured", payload["models"][0])
        aliases = {item["alias"] for item in payload["models"]}
        self.assertIn("gemini-flash", aliases)
        self.assertIn("gemini-pro", aliases)
        self.assertIn("model_family", payload["defaults"])

    def test_api_requires_bearer_token_when_configured(self):
        os.environ["DOC_EXTRACTOR_API_TOKEN"] = "super-secret-token"
        clear_runtime_settings_cache()

        response = self.client.get("/api/meta/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid or missing API token.")

    def test_api_accepts_valid_bearer_token_when_configured(self):
        os.environ["DOC_EXTRACTOR_API_TOKEN"] = "super-secret-token"
        clear_runtime_settings_cache()

        response = self.client.get(
            "/api/meta/",
            headers={"Authorization": "Bearer super-secret-token"},
        )

        self.assertEqual(response.status_code, 200)

    def test_web_endpoints_do_not_require_token_when_api_is_protected(self):
        os.environ["DOC_EXTRACTOR_API_TOKEN"] = "super-secret-token"
        clear_runtime_settings_cache()

        meta_response = self.client.get("/web/meta/")
        health_response = self.client.get("/web/health/")

        self.assertEqual(meta_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)

    @patch("app.main.execute_extraction_request")
    def test_extract_returns_stateless_payload(self, mock_execute):
        mock_execute.return_value = {
            "status": "success",
            "document_code": "04021",
            "result_type": "table",
            "document_schema": {"result_type": "table", "fields": [], "item_fields": []},
            "data": {"fields": {}, "items": [{"position": 1, "description": "Item"}], "count": 1},
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
        self.assertEqual(response.json()["result_type"], "table")
        self.assertEqual(response.json()["model_id"], "gpt-oss-120b")

    def test_extract_returns_400_for_unsupported_document_code(self):
        response = self.client.post(
            "/api/extract/",
            json={"document_code": "99999", "ocr_draft": "Invoice"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported document_code", response.json()["detail"])
