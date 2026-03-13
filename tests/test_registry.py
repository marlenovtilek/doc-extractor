import unittest

from extractor.documents.invoice.handler import InvoiceHandler
from extractor.documents.registry import (
    get_document_definition,
    get_document_handler,
    list_document_definitions,
    list_supported_document_codes,
)


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
        self.assertEqual(list_supported_document_codes(), ["04021"])

    def test_registry_lists_document_definitions_with_schema(self):
        definitions = list_document_definitions()

        self.assertEqual(definitions[0]["document_code"], "04021")
        self.assertEqual(definitions[0]["result_type"], "table")
        self.assertIn("schema", definitions[0])
        self.assertIn("item_fields", definitions[0]["schema"])

    def test_registry_raises_for_unknown_document_code(self):
        with self.assertRaises(ValueError) as exc:
            get_document_handler("99999")

        self.assertIn("Unsupported document_code '99999'", str(exc.exception))
