import unittest
from unittest.mock import patch

from extractor.documents.invoice import TechnicalDocumentHandler


class TechnicalDocumentHandlerTests(unittest.TestCase):
    @patch("extractor.documents.invoice.invoice.run_technical_document_extraction")
    def test_technical_document_handler_returns_table_payload(
        self,
        mock_run_technical_document_extraction,
    ):
        mock_run_technical_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "TD-55",
                    "document_date": "09/10/2025",
                },
                "items": [
                    {
                        "product_name": "Pressure Sensor PS-200",
                        "technical_description": "Range: 0-10 bar",
                        "hs_code": "9026202000",
                        "model": "PS-200",
                        "country_origin": "Germany",
                        "document_date": "09/10/2025",
                        "document_number": "TD-55",
                    }
                ],
                "count": 1,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = TechnicalDocumentHandler()
        response = handler.extract(ocr_draft="TD text", model="gemini")

        self.assertEqual(response["result_type"], "table")
        self.assertEqual(response["data"]["fields"]["document_number"], "TD-55")
        self.assertEqual(response["data"]["count"], 1)
        self.assertEqual(response["data"]["items"][0]["product_name"], "Pressure Sensor PS-200")

    @patch("extractor.documents.invoice.invoice.run_technical_document_extraction")
    def test_technical_document_handler_returns_empty_items_on_error(
        self,
        mock_run_technical_document_extraction,
    ):
        mock_run_technical_document_extraction.return_value = {
            "error": "No technical document items extracted",
            "metrics": {"primary_valid": False},
            "model_id": "gemini-2.5-flash",
        }

        handler = TechnicalDocumentHandler()
        response = handler.extract(ocr_draft="TD text", model="gemini")

        self.assertEqual(response["result_type"], "table")
        self.assertEqual(response["data"]["items"], [])
        self.assertEqual(response["data"]["count"], 0)
