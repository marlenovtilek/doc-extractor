import unittest

from extractor.documents.regular.contract import ContractHandler
from extractor.documents.invoice import InvoiceHandler, TechnicalDocumentHandler
from extractor.documents.regular.power_of_attorney import PowerOfAttorneyHandler
from extractor.documents.registry import (
    get_document_definition,
    get_document_handler,
    list_document_definitions,
    list_supported_document_codes,
)
from extractor.documents.regular.supply_contract import SupplyContractHandler


class DocumentRegistryTests(unittest.TestCase):
    def test_registry_returns_invoice_handler_for_04021(self):
        handler = get_document_handler("04021")

        self.assertIsInstance(handler, InvoiceHandler)
        self.assertEqual(handler.document_code, "04021")
        self.assertEqual(handler.result_type, "table")

    def test_registry_returns_invoice_definition_with_schema(self):
        definition = get_document_definition("04021")

        self.assertEqual(definition.document_code, "04021")
        self.assertEqual(definition.label, "Invoice")
        self.assertEqual(definition.schema.result_type, "table")
        self.assertTrue(definition.schema.item_fields)

    def test_registry_lists_supported_codes(self):
        self.assertEqual(
            list_supported_document_codes(),
            [
                "04021",
                "03011",
                "00012",
                "11019",
                "000011",
                "00002",
                "000004",
                "09022",
                "22222",
                "9012",
                "01011",
                "11111",
                "11014",
                "11116",
                "11114",
                "010000",
                "01207",
                "00010",
                "01201",
                "09999",
                "10999",
                "ELSE",
            ],
        )

    def test_registry_lists_document_definitions_with_schema(self):
        definitions = list_document_definitions()

        self.assertEqual(definitions[0]["document_code"], "04021")
        self.assertEqual(definitions[0]["result_type"], "table")
        self.assertIn("schema", definitions[0])
        self.assertIn("item_fields", definitions[0]["schema"])
        by_code = {item["document_code"]: item for item in definitions}
        self.assertEqual(by_code["03011"]["result_type"], "object")
        self.assertIn("fields", by_code["03011"]["schema"])
        self.assertEqual(by_code["00012"]["result_type"], "object")
        self.assertEqual(by_code["11019"]["result_type"], "object")
        self.assertEqual(by_code["09022"]["result_type"], "table")
        self.assertIn("item_fields", by_code["09022"]["schema"])

    def test_registry_returns_contract_handler_for_03011(self):
        handler = get_document_handler("03011")

        self.assertIsInstance(handler, ContractHandler)
        self.assertEqual(handler.document_code, "03011")
        self.assertEqual(handler.result_type, "object")

    def test_registry_returns_contract_definition_with_schema(self):
        definition = get_document_definition("03011")

        self.assertEqual(definition.document_code, "03011")
        self.assertEqual(definition.label, "Contract")
        self.assertEqual(definition.schema.result_type, "object")
        self.assertTrue(definition.schema.fields)

    def test_registry_returns_supply_contract_handler_for_00012(self):
        handler = get_document_handler("00012")

        self.assertIsInstance(handler, SupplyContractHandler)
        self.assertEqual(handler.document_code, "00012")
        self.assertEqual(handler.result_type, "object")

    def test_registry_returns_power_of_attorney_handler_for_11019(self):
        handler = get_document_handler("11019")

        self.assertIsInstance(handler, PowerOfAttorneyHandler)
        self.assertEqual(handler.document_code, "11019")
        self.assertEqual(handler.result_type, "object")

    def test_registry_returns_technical_document_handler_for_09022(self):
        handler = get_document_handler("09022")

        self.assertIsInstance(handler, TechnicalDocumentHandler)
        self.assertEqual(handler.document_code, "09022")
        self.assertEqual(handler.result_type, "table")

    def test_registry_raises_for_unknown_document_code(self):
        with self.assertRaises(ValueError) as exc:
            get_document_handler("99999")

        self.assertIn("Unsupported document_code '99999'", str(exc.exception))
