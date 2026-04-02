import unittest

from extractor.normalizers.currency import finalize_items, infer_currency_from_text


class InvoiceNormalizationTests(unittest.TestCase):
    def test_country_and_cost_normalization(self) -> None:
        items = [
            {
                "description": "Widget",
                "quantity": 20,
                "price": 8.82,
                "country_origin": "DE",
                "country_origin_code": "Кыргызстан",
                "country_sender": "DE",
                "currency_code": "EUR",
            }
        ]

        normalized = finalize_items(items, [])
        self.assertEqual(normalized[0]["country_origin"], "Германия")
        self.assertEqual(normalized[0]["country_origin_code"], "KGZ")
        self.assertEqual(normalized[0]["country_sender"], "Германия")
        self.assertEqual(normalized[0]["currency_name"], "Euro")
        self.assertEqual(normalized[0]["cost"], 176.4)

    def test_infer_currency_from_ocr_header(self) -> None:
        code, name = infer_currency_from_text(
            "Payment Terms: Cash before Delivery Total Amount (EUR): 34.839,63",
            [],
        )
        self.assertEqual(code, "EUR")
        self.assertEqual(name, "Euro")

    def test_country_display_normalization_from_english_and_uppercase(self) -> None:
        items = [
            {"description": "A", "country_origin": "КИТАЙ", "country_sender": "Germany"},
        ]
        normalized = finalize_items(items, [])
        self.assertEqual(normalized[0]["country_origin"], "Китай")
        self.assertEqual(normalized[0]["country_sender"], "Германия")


if __name__ == "__main__":
    unittest.main()
