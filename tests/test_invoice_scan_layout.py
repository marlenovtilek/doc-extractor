import unittest

from extractor.invoice.invoice_scan_layout import extract_scan_table_invoice


class InvoiceScanLayoutTests(unittest.TestCase):
    def test_extract_scan_table_invoice_parses_numbered_rows(self) -> None:
        ocr_text = """
        INVOICE No 000223420
        Date 12.12.2025
        Currency USD
        Description HS Code Qty Unit Price Amount
        1 Widget A CN 8471490000 1 pcs 27 280 27 280
        2 Widget B DE 8471490001 2 pcs 500 1 000
        Итого 28 280
        """

        result = extract_scan_table_invoice(ocr_text)

        self.assertTrue(result["looks_like_scan_table"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["description"], "Widget A")
        self.assertEqual(result["items"][0]["hs_code"], "8471490000")
        self.assertEqual(result["items"][0]["quantity"], 1)
        self.assertEqual(result["items"][0]["unit"], "pcs")
        self.assertEqual(result["items"][0]["price"], 27280)
        self.assertEqual(result["items"][0]["cost"], 27280)
        self.assertEqual(result["items"][0]["country_origin_code"], "CN")
        self.assertEqual(result["items"][0]["document_number"], "000223420")


if __name__ == "__main__":
    unittest.main()
