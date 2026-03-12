import unittest

from extractor.documents.invoice.handler import InvoiceHandler
from extractor.documents.registry import get_document_handler, list_supported_document_codes


class DocumentRegistryTests(unittest.TestCase):
    def test_registry_returns_invoice_handler_for_04021(self):
        handler = get_document_handler("04021")

        self.assertIsInstance(handler, InvoiceHandler)
        self.assertEqual(handler.document_code, "04021")
        self.assertEqual(handler.result_type, "table")

    def test_registry_lists_supported_codes(self):
        self.assertEqual(list_supported_document_codes(), ["04021"])

    def test_registry_raises_for_unknown_document_code(self):
        with self.assertRaises(ValueError) as exc:
            get_document_handler("99999")

        self.assertIn("Unsupported document_code '99999'", str(exc.exception))
