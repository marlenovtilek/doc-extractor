import unittest
from unittest.mock import patch

from extractor.documents.regular.cmr import CMRHandler
from extractor.documents.regular.contract import ContractHandler
from extractor.documents.regular.power_of_attorney import PowerOfAttorneyHandler
from extractor.documents.regular.supply_contract import SupplyContractHandler
from extractor.documents.regular.taxpayer_registration_card import TaxpayerRegistrationCardHandler
from extractor.documents.regular.trusted_passport_poa import TrustedPassportPowerOfAttorneyHandler


class ContractHandlerTests(unittest.TestCase):
    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_contract_handler_returns_object_fields(self, mock_run_object_document_extraction):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "CT-2024/117",
                    "document_date": "12/11/2024",
                    "parties": ["Acme GmbH", "Global Tech LLC"],
                    "subject": "Supply of industrial spare parts",
                    "description": "Контракт на поставку промышленных запасных частей.",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = ContractHandler()
        response = handler.extract(ocr_draft="Contract text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["items"], [])
        self.assertEqual(response["data"]["count"], 0)
        self.assertEqual(response["data"]["fields"]["document_number"], "CT-2024/117")
        self.assertEqual(response["data"]["fields"]["parties"][0], "Acme GmbH")

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_contract_handler_returns_empty_fields_on_error(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "error": "No contract fields extracted",
            "metrics": {"primary_valid": False},
            "model_id": "gemini-2.5-flash",
        }

        handler = ContractHandler()
        response = handler.extract(ocr_draft="Contract text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["items"], [])
        self.assertEqual(response["data"]["count"], 0)
        self.assertIn("document_number", response["data"]["fields"])
        self.assertIsNone(response["data"]["fields"]["document_number"])

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_supply_contract_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "SUP-77/24",
                    "document_date": "14/09/2024",
                    "description": "Договор поставки промышленных смазочных материалов.",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = SupplyContractHandler()
        response = handler.extract(ocr_draft="Supply contract text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["document_number"], "SUP-77/24")
        self.assertEqual(response["data"]["count"], 0)

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_power_of_attorney_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "POA-22/2025",
                    "authorized_person": "Aibek Omuraliev",
                    "trusted_person": "Dinara Sadykova",
                    "document_date": "03/02/2025",
                    "description": "Доверенность",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = PowerOfAttorneyHandler()
        response = handler.extract(ocr_draft="POA text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["authorized_person"], "Aibek Omuraliev")
        self.assertEqual(response["data"]["fields"]["trusted_person"], "Dinara Sadykova")

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_trusted_passport_poa_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "TP-14/2025",
                    "authorized_person": "Bekzat Imanov",
                    "trusted_person": "Aizada Toktorova",
                    "document_date": "21/01/2025",
                    "description": "Power of Attorney with trusted persons passport",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = TrustedPassportPowerOfAttorneyHandler()
        response = handler.extract(ocr_draft="Trusted POA text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["document_number"], "TP-14/2025")
        self.assertEqual(response["data"]["fields"]["authorized_person"], "Bekzat Imanov")

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_cmr_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "442190",
                    "document_date": "18/09/2025",
                    "description": "Международная транспортная накладная CMR.",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = CMRHandler()
        response = handler.extract(ocr_draft="CMR text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["document_number"], "442190")
        self.assertEqual(response["data"]["count"], 0)

    @patch("extractor.documents.object_core.run_object_document_extraction")
    def test_taxpayer_registration_card_handler_returns_object_fields(
        self,
        mock_run_object_document_extraction,
    ):
        mock_run_object_document_extraction.return_value = {
            "result": {
                "fields": {
                    "document_number": "12345678901234",
                    "document_date": "07/11/2024",
                    "description": "Карточка регистрации налогоплательщика формы STI-025.",
                },
                "items": [],
                "count": 0,
            },
            "metrics": {"primary_valid": True},
            "model_id": "gemini-2.5-flash",
        }

        handler = TaxpayerRegistrationCardHandler()
        response = handler.extract(ocr_draft="STI text", model="gemini")

        self.assertEqual(response["result_type"], "object")
        self.assertEqual(response["data"]["fields"]["document_number"], "12345678901234")
        self.assertEqual(response["data"]["count"], 0)
