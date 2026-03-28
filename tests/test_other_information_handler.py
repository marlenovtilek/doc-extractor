import unittest
from unittest.mock import patch

from extractor.documents.regular.other_information import OtherInformationHandler


class OtherInformationHandlerTests(unittest.TestCase):
    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_other_information_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "REF-15",
                    "document_date": "12/03/2026",
                    "hs_code": "85181090",
                    "description": "Письмо о товаре",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = OtherInformationHandler()
        response = handler.extract(ocr_draft="Other info text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["document_number"], "REF-15")
        self.assertEqual(response["data"]["fields"]["hs_code"], "85181090")
        self.assertEqual(response["data"]["count"], 0)

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_other_information_handler_returns_empty_fields_on_error(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "error": "No Other Information fields extracted",
            "metrics": {"primary_valid": False},
            "model_id": "gemini-2.5-flash",
        }

        handler = OtherInformationHandler()
        response = handler.extract(ocr_draft="Other info text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["items"], [])
        self.assertEqual(response["data"]["count"], 0)
        self.assertIsNone(response["data"]["fields"]["document_number"])
        self.assertIsNone(response["data"]["fields"]["hs_code"])
