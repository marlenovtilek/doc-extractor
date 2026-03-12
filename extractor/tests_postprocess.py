import unittest

from extractor.postprocess import deduplicate_items, extract_structured_pipe_items, filter_ocr_anomalies


class StructuredPipeExtractionTests(unittest.TestCase):
    def test_extract_structured_pipe_items_parses_article_led_and_marker_rows(self):
        context = """=== CURRENCY DATABASE (REFERENCE) ===
[{"code":"USD","name":"US Dollar"}]

=== INVOICE CONTENT ===
Invoice Number: 000223420
Currency: USD
| Part No | Description | Origin | Qty | Price | Total |
| 506992 | XSW 1-ME3-GB | МИКРОФОН | 3021068228725 | Тайвань | 85181090 | 4,00 | 1,40 | 2,86 | 220,00 | 880,00 |
| 507115 | XSW 1-835-A | МИКРОФОН | 3021118073325 | Тайвань | 85181090 | 4,00 | 2,00 | 3,46 | 192,50 | 770,00 |
| + | 507122 | XSW 2-ME2-A | МИКРОФОН | 3021116201325 | Тайвань | 85181090 | 3,00 | 06'0 | 2,00 | 264,00 | 792,00 |
| 200000 | ADP UHF (470-1075 MHZ) | АНТЕННА | 3021094804825 | Китай | 85177100 | 00,01 | 0.50 | 4.16 | 71,50 | 715,00 |
"""

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["position"], 506992)
        self.assertEqual(items[0]["hs_code"], "85181090")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 220.0)
        self.assertEqual(items[0]["price"], 880.0)
        self.assertEqual(items[2]["position"], 507122)
        self.assertIn("XSW 2-ME2-A", items[2]["description"])
        self.assertEqual(items[2]["cost"], 264.0)
        self.assertEqual(items[2]["price"], 792.0)

    def test_extract_structured_pipe_items_uses_best_total_pair_from_noisy_tail(self):
        context = """=== CURRENCY DATABASE (REFERENCE) ===
[{"code":"USD","name":"US Dollar"}]

=== INVOICE CONTENT ===
| 508701 | FW-D ME2 SET (R1-6) | МИКРОФОН | 3021082411025 | Румыния | 85181090 | 12,00 | 33,60 | 37,99 | 412,50 | 4950,00 | | 2 8 |
| 509300 | EW DX 835 5 SET (QL 9) SET | МИКРОФОН | 3021116936925 | Румыния | 85181090 | 3,00 | 9,00 | 10,10 | 605 00 | 1210.00 |
| 508935 | ME 2 | МИКРОФОН | 3021107987825 | филиппины | 05103000 | 1 00 | 0.30 | 19'0 | 55,00 | 55,00 |
"""

        items = extract_structured_pipe_items(context)
        by_position = {item["position"]: item for item in items}

        self.assertEqual(by_position[508701]["cost"], 412.5)
        self.assertEqual(by_position[508701]["price"], 4950.0)
        self.assertEqual(by_position[509300]["quantity"], 3.0)
        self.assertEqual(by_position[509300]["cost"], 605.0)
        self.assertEqual(by_position[509300]["price"], 1210.0)
        self.assertEqual(by_position[508935]["quantity"], 1.0)
        self.assertEqual(by_position[508935]["cost"], 55.0)
        self.assertEqual(by_position[508935]["price"], 55.0)

    def test_filter_ocr_anomalies_drops_obvious_numeric_corruption(self):
        items = [
            {
                "position": 507115,
                "description": "XSW 1-835-A",
                "hs_code": "85181090",
                "quantity": 4.0,
                "cost": 192.5,
                "price": 770.0,
            },
            {
                "position": 206980,
                "description": "XSW 1-ME2-A",
                "hs_code": "85181090",
                "quantity": 9009.0,
                "cost": 209.0,
                "price": 1254.0,
            },
            {
                "position": 200000,
                "description": "ADP UHF",
                "hs_code": "851//100",
                "quantity": 0.01,
                "cost": 71.5,
                "price": 715.0,
            },
        ]

        filtered = filter_ocr_anomalies(items)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["position"], 507115)
        self.assertEqual(filtered[0]["hs_code"], "85181090")

    def test_deduplicate_items_uses_position_hs_quantity_price(self):
        items = [
            {
                "position": 507115,
                "description": "XSW 1-835-A",
                "hs_code": "85181090",
                "quantity": 4.0,
                "cost": 192.5,
                "price": 770.0,
            },
            {
                "position": 507115,
                "description": "XSW 1-835-A alt",
                "hs_code": "85181090",
                "quantity": 4.0,
                "cost": 193.0,
                "price": 770.0,
            },
            {
                "position": 507115,
                "description": "XSW 1-835-A other total",
                "hs_code": "85181090",
                "quantity": 4.0,
                "cost": 192.5,
                "price": 771.0,
            },
        ]

        deduped = deduplicate_items(items)

        self.assertEqual(len(deduped), 2)
