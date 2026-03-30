import unittest
from pathlib import Path
from unittest.mock import patch

from extractor.documents.invoice import (
    _extract_hs_last_item,
    _extract_sparse_hs_item_without_country,
    _trim_item_line,
    _extract_inline_blob_pipe_rows,
    clean_text,
    deduplicate_items,
    extract_structured_pipe_items,
    run_invoice_extraction,
)
from extractor.documents.invoice.invoice import InvoiceHandler
from extractor.documents.invoice.invoice import run_invoice_structured_only_extraction
from extractor.documents.invoice.invoice_header import build_header_metadata
from extractor.documents.invoice.invoice_postprocess import (
    _prune_shadow_rows,
    _sanitize_country_origin,
    normalize_invoice_items,
    prepare_invoice_items_for_merge,
)
from extractor.documents.invoice.invoice_postprocess_dedup import filter_ocr_anomalies


class InvoiceParserFirstTests(unittest.TestCase):
    def test_run_invoice_structured_only_extraction_handles_invoice_126_fixture(self):
        fixture = Path(__file__).resolve().parent.parent / "invoice_126.txt"
        self.assertTrue(fixture.exists())

        result = run_invoice_structured_only_extraction(fixture.read_text(encoding="utf-8"))

        positions = [int(item["position"]) for item in result["result"]["items"]]
        self.assertEqual(result["result"]["count"], 126)
        self.assertEqual(positions, list(range(1, 127)))

    def test_run_invoice_structured_only_extraction_handles_invoice_217_fixture(self):
        fixture = Path(__file__).resolve().parent.parent / "invoice_217.txt"
        self.assertTrue(fixture.exists())

        result = run_invoice_structured_only_extraction(fixture.read_text(encoding="utf-8"))

        positions = [int(item["position"]) for item in result["result"]["items"]]
        self.assertEqual(result["result"]["count"], 217)
        self.assertEqual(positions, list(range(1, 218)))

    def test_deduplicate_items_keeps_rows_with_different_declaration_refs(self):
        items = [
            {
                "position": 507115,
                "description": "XSW 1-835-A МИКРОФОН",
                "hs_code": "85181090",
                "quantity": 2.0,
                "price": 962.5,
                "cost": 481.25,
                "country_origin": "Тайвань",
                "_decl_ref": "3021116201325",
            },
            {
                "position": 507115,
                "description": "XSW 1-835-A МИКРОФОН",
                "hs_code": "85181090",
                "quantity": 2.0,
                "price": 962.5,
                "cost": 481.25,
                "country_origin": "Тайвань",
                "_decl_ref": "3021110059225",
            },
        ]

        result = deduplicate_items(items)

        self.assertEqual(len(result), 2)

    def test_deduplicate_items_drops_no_hs_shadow_when_hs_row_exists(self):
        items = [
            {
                "position": 1287724,
                "description": "Кронштейн",
                "hs_code": "8302300009",
                "quantity": 3.0,
                "price": 18.45,
                "cost": 6.15,
                "country_origin": "PL",
            },
            {
                "position": 1287724,
                "description": "Console",
                "hs_code": None,
                "quantity": 3.0,
                "price": 18.45,
                "cost": 6.15,
                "country_origin": "PL",
            },
        ]

        result = deduplicate_items(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["hs_code"], "8302300009")

    def test_deduplicate_items_prefers_cleaner_latin_description_over_noisy_ocr(self):
        items = [
            {
                "position": 999330,
                "description": "MINIPRA INIONO",
                "hs_code": None,
                "quantity": 30.0,
                "price": 93.9,
                "cost": 3.13,
                "country_origin": "SE",
                "_line_sig": ("999330", "bolt", "minipra iniono", "se", "3,13", "93,90", "net w"),
            },
            {
                "position": 999330,
                "description": "Bolt",
                "hs_code": None,
                "quantity": 30.0,
                "price": 93.9,
                "cost": 3.13,
                "country_origin": "SE",
                "_line_sig": ("999330", "bolt", "se", "30", "3,13", "93,90"),
            },
        ]

        result = deduplicate_items(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["description"], "Bolt")

    def test_filter_ocr_anomalies_drops_marker_heavy_invalid_country_shadow(self):
        items = [
            {
                "position": 3141430,
                "description": "O - Ming",
                "hs_code": "4016930005",
                "quantity": 20.0,
                "price": 90.7,
                "cost": 3.0,
                "country_origin": "передатчика бака",
                "_line_sig": (
                    "3141430",
                    "o - ming",
                    "передатчика бака",
                    "-,",
                    "•",
                    "• • •",
                    "20",
                    "3.00",
                    "90.70",
                    "4016930005",
                ),
            }
        ]

        self.assertEqual(filter_ocr_anomalies(items), [])

    def test_filter_ocr_anomalies_drops_leading_zero_shadow_with_invalid_country(self):
        items = [
            {
                "position": 848700,
                "description": "трубки кондиционера 21.8х3.5",
                "hs_code": "401000000",
                "quantity": 20.0,
                "price": 30.0,
                "cost": 1.5,
                "country_origin": "FK",
                "_line_sig": (
                    "0848700",
                    "o-king",
                    "трубки кондиционера 21.8х3.5",
                    "fk",
                    "20",
                    "4,50",
                    "30,00",
                    "401000000",
                ),
            }
        ]

        self.assertEqual(filter_ocr_anomalies(items), [])

    def test_extract_inline_blob_pipe_rows_recovers_embedded_rows(self):
        line = (
            "| 1511 | MKH 416-P48113 | МИКРОФОН | 3021089715825 | Германия | "
            "85181090 | 2,00 | 1,47 | 2,20 | 250,00 | 1100,00 | | "
            "45.56 E 845-5 MINKPODOH 3021118073325 Германия 85181090 "
            "5,00 3,00 4,83 55,00 3 4645 A1031U UHFANTENINA MINKPODOH "
            "3021105987825 Германия 85177100 1,00 1,37 110,00 1 |"
        )

        embedded = _extract_inline_blob_pipe_rows(line)

        self.assertEqual(len(embedded), 2)
        self.assertIn("| 4556 |", embedded[0])
        self.assertIn("| 275,00 |", embedded[0])
        self.assertIn("| 4645 |", embedded[1])

    def test_clean_text_splits_sparse_embedded_pipe_rows(self):
        raw_text = (
            "| 984 | MD 421-II | МИКРОФОН | 3021082411025 | Румыния | 85181090 | "
            "1,00 | 0,88 | 1,25 | 236,50 | 236,50 | | 7 6 | | 1511 | | "
            "MKH 416-P48113 | | МИКРОФОН | | 3021089715825 | | Германия | | "
            "85181090 | | 2,00 | | 1,47 | | 2,20 | | 250,00 | | 1100,00 |"
        )

        cleaned = clean_text(raw_text, "[]")
        items = extract_structured_pipe_items(cleaned)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["position"], 984)
        self.assertIsNone(items[1]["position"])
        self.assertEqual(items[1]["part_no"], "1511")
        self.assertEqual(items[1]["price"], 1100.0)

    def test_clean_text_expands_stacked_marker_html_rows(self):
        raw_text = (
            "| 48<br>49 | 30731907<br>30736724 | Protection<br>Washer | "
            "Ограждение ремня<br>Проставка под пружину (зад подвеска) | "
            "EE<br>DE | 3<br>1 | 6,24<br>12,40 | 18,72<br>12,40 | "
            "8409990009<br>4016995 <b>7</b> 09 |"
        )

        cleaned = clean_text(raw_text, "[]")
        items = extract_structured_pipe_items(cleaned)
        by_position = {item["position"]: item for item in items}

        self.assertEqual(len(items), 2)
        self.assertEqual(by_position[48]["part_no"], "30731907")
        self.assertEqual(by_position[48]["hs_code"], "8409990009")
        self.assertEqual(by_position[48]["quantity"], 3.0)
        self.assertEqual(by_position[48]["cost"], 6.24)
        self.assertEqual(by_position[48]["price"], 18.72)
        self.assertEqual(by_position[49]["part_no"], "30736724")
        self.assertEqual(by_position[49]["hs_code"], "4016995709")
        self.assertEqual(by_position[49]["quantity"], 1.0)
        self.assertEqual(by_position[49]["cost"], 12.4)
        self.assertEqual(by_position[49]["price"], 12.4)

    def test_clean_text_rehydrates_flattened_invoice_ocr_blob(self):
        raw_text = (
            "![](_page_5_Picture_0.jpeg) ## Invoice Page: 1/15 Date: 21.07.2025 "
            "Invoice Number: 206447 Customer No: 10210 Incoterms: CPT - Bishkek "
            "| POS | Part No | Description | Origin | Qty | Price | Total | "
            "|-----|------------------------|--------------|--------|-----|-------|-------| "
            "| 2 | 1161748 | Grease | SE | 20 | 8,82 | 176,40 | "
            "| | Order date: 18.06.2025 | - AVIA | | | | | "
            "| 3 | 1233068 | O - Ring | JP | 70 | 6,56 | 459,20 | "
            "| | Order date: 18.06.2025 | - AVIA | | | | | "
            "Carry-Over: 635,60 ![](_page_6_Picture_0.jpeg) 2/15"
        )

        cleaned = clean_text(raw_text, "[]")
        items = extract_structured_pipe_items(cleaned)
        positions = [item["position"] for item in items]

        self.assertIn("=== INVOICE CONTENT ===", cleaned)
        self.assertIn("\n| POS | Part No | Description | Origin | Qty | Price | Total |\n", cleaned)
        self.assertIn("\nCarry-Over: 635,60\n", cleaned)
        self.assertEqual(positions, [2, 3])
        self.assertEqual([item["part_no"] for item in items], ["1161748", "1233068"])
        self.assertEqual(items[0]["quantity"], 20.0)
        self.assertEqual(items[0]["price"], 176.4)
        self.assertEqual(items[1]["quantity"], 70.0)
        self.assertEqual(items[1]["price"], 459.2)

    def test_clean_text_rehydrates_embedded_order_date_chain_with_notice_row(self):
        raw_text = (
            "| POS | Part No | Description | Origin | Qty | Price | Total | | 174 | 980367\n"
            "Order date: 18.0 | Nut 06.2025 - AVIA | DE | 10 | 0,73 | 7,30 | | 175 | 980740\n"
            "Order date: 24.0 | Nut 06.2025 - AVIA | DE | 30 | 1,04 | 31,20 | | 176 | 980740\n"
            "Order date: 18.0 | Nut 06.2025 - AVIA | DE | 30 | 1,04 | 31,20 | | 177 | 30769462\n"
            "Order date: 24.0\n"
            "Please beware: | Screw 06.2025 - AVIA Your used Part No 982754 is outdated, ple | "
            "DE case use the current Part No for yo | 20 ur future orders. | 1,00 | 20,00 | | 178 | 982761\n"
            "Order date: 24.0 | Screw 96,2025 - AVIA | DE | 10 | 1,11 | 11,10 |"
        )

        cleaned = clean_text(raw_text, "[]")
        items = extract_structured_pipe_items(cleaned)
        by_position = {item["position"]: item for item in items}

        self.assertIn(177, by_position)
        self.assertEqual(by_position[177]["part_no"], "30769462")
        self.assertEqual(by_position[177]["description"], "Screw")
        self.assertEqual(by_position[177]["quantity"], 20.0)
        self.assertEqual(by_position[177]["price"], 20.0)

    def test_extract_structured_pipe_items_keeps_zero_total_service_row(self):
        context = "=== INVOICE CONTENT ===\n| 1 | Frachtkosten | Freight Cost | | | 1 | 0,00 | 0,00|\n"

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 1)
        self.assertEqual(items[0]["description"], "Frachtkosten")
        self.assertEqual(items[0]["quantity"], 1.0)
        self.assertEqual(items[0]["cost"], 0.0)
        self.assertEqual(items[0]["price"], 0.0)

    def test_normalize_invoice_items_keeps_zero_total_service_row(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 1,
                    "description": "Frachtkosten",
                    "hs_code": None,
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 0.0,
                    "price": 0.0,
                    "country_origin": None,
                    "_line_sig": ("1", "frachtkosten", "1", "0,00", "0,00"),
                }
            ],
            {},
            [],
            preserve_exact_line_duplicates=True,
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["description"], "Frachtkosten")
        self.assertEqual(normalized[0]["cost"], 0.0)
        self.assertEqual(normalized[0]["price"], 0.0)

    def test_normalize_invoice_items_does_not_spread_country_to_service_charge_row(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 1,
                    "description": "Clamp",
                    "hs_code": "7326909409",
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 10.0,
                    "price": 10.0,
                    "country_origin": "DE",
                },
                {
                    "position": 2,
                    "description": "Frachtkosten",
                    "hs_code": None,
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 5.0,
                    "price": 5.0,
                    "country_origin": None,
                },
            ],
            {},
            [],
            preserve_exact_line_duplicates=True,
        )

        by_position = {item["position"]: item for item in normalized}
        self.assertEqual(by_position[1]["country_origin"], "Германия")
        self.assertIsNone(by_position[2]["country_origin"])

    def test_normalize_invoice_items_preserves_six_digit_hs_code(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 1,
                    "description": "Widget valve",
                    "hs_code": "847130",
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 10.0,
                    "price": 10.0,
                    "country_origin": "DE",
                }
            ],
            {},
            [],
            preserve_exact_line_duplicates=True,
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["hs_code"], "847130")

    def test_extract_structured_pipe_items_salvages_total_divided_by_quantity(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 4514 | E 835-5 | МИКРОФОН | 3021107987825 | Германия | 85181090 | 10,00 | 5,80 | 9,46 | 22,00 | 550,00 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["position"])
        self.assertEqual(items[0]["part_no"], "4514")
        self.assertEqual(items[0]["quantity"], 10.0)
        self.assertEqual(items[0]["cost"], 55.0)
        self.assertEqual(items[0]["price"], 550.0)

    def test_extract_structured_pipe_items_infers_quantity_from_total_and_unit_price(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 206980 | XSW 1-ME2-A | Микрофон | 3021076350525 | Тайвань | "
            "85181090 | 900'9 | 7,43 | 6,62 | 209,00 | 1254,00 | S |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["position"])
        self.assertEqual(items[0]["part_no"], "206980")
        self.assertEqual(items[0]["quantity"], 6.0)
        self.assertEqual(items[0]["cost"], 209.0)
        self.assertEqual(items[0]["price"], 1254.0)

    def test_extract_structured_pipe_items_repairs_trailing_zero_loss(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 502577 | 502577 502577 502577 502579 MMD 845-1 BK МИКРОФОН | "
            "3021107987825 | Германия | 85181090 | 0,9 | 09'0 | 2,80 | 55,00 | 49,5 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["position"])
        self.assertEqual(items[0]["part_no"], "502577")
        self.assertEqual(items[0]["quantity"], 9.0)
        self.assertEqual(items[0]["cost"], 55.0)
        self.assertEqual(items[0]["price"], 495.0)

    def test_extract_structured_pipe_items_supports_compact_hs_last_schema(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 31 | 30650846 | Belt | Ремень навесного оборудования B4164S3 | IT | 1 | 14,26 | 14,26 | 4010390000 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 31)
        self.assertEqual(items[0]["part_no"], "30650846")
        self.assertEqual(items[0]["hs_code"], "4010390000")
        self.assertEqual(items[0]["quantity"], 1.0)
        self.assertEqual(items[0]["cost"], 14.26)
        self.assertEqual(items[0]["price"], 14.26)
        self.assertEqual(items[0]["description"], "Ремень навесного оборудования B4164S3")
        self.assertEqual(items[0]["country_origin"], "IT")

    def test_extract_structured_pipe_items_parses_numeric_cells_wrapped_in_ocr_noise(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 21 | 30640643 | Clip | Держатель порога | SE DE | 50 | TC 0,92 T | 46,00 | 3926909709 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 21)
        self.assertEqual(items[0]["part_no"], "30640643")
        self.assertEqual(items[0]["description"], "Держатель порога")
        self.assertEqual(items[0]["country_origin"], "SE")
        self.assertEqual(items[0]["quantity"], 50.0)
        self.assertEqual(items[0]["cost"], 0.92)
        self.assertEqual(items[0]["price"], 46.0)
        self.assertEqual(items[0]["hs_code"], "3926909709")

    def test_extract_structured_pipe_items_merges_split_marker_head_and_tail_rows(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 21 | 30640643 | Clip | Держатель порога | SE DE\n"
            "| 50 | TC 0,92 T | 46,00 | 3926909709 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 21)
        self.assertEqual(items[0]["part_no"], "30640643")
        self.assertEqual(items[0]["description"], "Держатель порога")
        self.assertEqual(items[0]["country_origin"], "SE")
        self.assertEqual(items[0]["quantity"], 50.0)
        self.assertEqual(items[0]["cost"], 0.92)
        self.assertEqual(items[0]["price"], 46.0)
        self.assertEqual(items[0]["hs_code"], "3926909709")

    def test_extract_structured_pipe_items_merges_repeated_item_head_with_numeric_continuation(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 108 | 8653344 | Hose | картерных газов |\n"
            "| 108 | 8653344 | Hose | A PARTON OF THE PROPERTY OF THE PARTON OF THE PARTON OF TH | 4 | 18,83 | 75,32 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 108)
        self.assertEqual(items[0]["part_no"], "8653344")
        self.assertEqual(items[0]["description"], "Шланг картерных газов")
        self.assertEqual(items[0]["country_origin"], "Неизвестно")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 18.83)
        self.assertEqual(items[0]["price"], 75.32)

    def test_extract_structured_pipe_items_merges_partial_description_head_with_compact_tail(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 38 | 30683358 | Clip | Фиксатор троса стояночного тормоза | | 2 |\n"
            "| 38 | 30683358 | Clip | DE | 2 | 8,76 | 17,52 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 38)
        self.assertEqual(items[0]["part_no"], "30683358")
        self.assertEqual(items[0]["description"], "Фиксатор троса стояночного тормоза")
        self.assertEqual(items[0]["country_origin"], "DE")
        self.assertEqual(items[0]["quantity"], 2.0)
        self.assertEqual(items[0]["cost"], 8.76)
        self.assertEqual(items[0]["price"], 17.52)

    def test_extract_structured_pipe_items_merges_split_row_across_page_break_noise(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 38 | 30683358 | Clip | Фиксатор троса стояночного |\n"
            "Carry-Over: 2.224,67\n"
            "![](_page_8_Picture_0.jpeg)\n"
            "4/15\n"
            "| 38 | 30683358 | Clip | DE | 2 | 8,76 | 17,52 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 38)
        self.assertEqual(items[0]["part_no"], "30683358")
        self.assertEqual(items[0]["description"], "Фиксатор троса стояночного")
        self.assertEqual(items[0]["country_origin"], "DE")
        self.assertEqual(items[0]["quantity"], 2.0)
        self.assertEqual(items[0]["cost"], 8.76)
        self.assertEqual(items[0]["price"], 17.52)

    def test_extract_structured_pipe_items_merges_split_row_across_order_date_and_avia_noise(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 38 | 30683358 | Clip | Фиксатор троса стояночного |\n"
            "Order date: 24.06.2025\n"
            "- AVIA\n"
            "| 38 | 30683358 | Clip | DE | 2 | 8,76 | 17,52 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 38)
        self.assertEqual(items[0]["part_no"], "30683358")
        self.assertEqual(items[0]["description"], "Фиксатор троса стояночного")
        self.assertEqual(items[0]["country_origin"], "DE")
        self.assertEqual(items[0]["quantity"], 2.0)
        self.assertEqual(items[0]["cost"], 8.76)
        self.assertEqual(items[0]["price"], 17.52)

    def test_extract_structured_pipe_items_merges_split_row_across_short_ocr_fragment_noise(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 108 | 8653344 | Hose | картерных газов |\n"
            "Water Control\n"
            "| 108 | 8653344 | Hose | 4 | 18,83 | 75,32 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 108)
        self.assertEqual(items[0]["part_no"], "8653344")
        self.assertEqual(items[0]["description"], "Шланг картерных газов")
        self.assertEqual(items[0]["country_origin"], "Неизвестно")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 18.83)
        self.assertEqual(items[0]["price"], 75.32)

    def test_extract_structured_pipe_items_merges_split_row_across_short_pipe_noise(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 108 | 8653344 | Hose | картерных газов |\n"
            "| Water Control |\n"
            "| 108 | 8653344 | Hose | 4 | 18,83 | 75,32 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 108)
        self.assertEqual(items[0]["part_no"], "8653344")
        self.assertEqual(items[0]["description"], "Шланг картерных газов")
        self.assertEqual(items[0]["country_origin"], "Неизвестно")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 18.83)
        self.assertEqual(items[0]["price"], 75.32)

    def test_extract_structured_pipe_items_merges_split_row_across_short_pipe_noise_with_one_number(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 108 | 8653344 | Hose | картерных газов |\n"
            "| Water Control | 100 |\n"
            "| 108 | 8653344 | Hose | 4 | 18,83 | 75,32 |\n"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 108)
        self.assertEqual(items[0]["part_no"], "8653344")
        self.assertEqual(items[0]["description"], "Шланг картерных газов")
        self.assertEqual(items[0]["country_origin"], "Неизвестно")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 18.83)
        self.assertEqual(items[0]["price"], 75.32)

    def test_extract_structured_pipe_items_supports_compact_no_hs_schema(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 72 | 31392312 | Gasket | DE | 5 | 42,63 | 213,15 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 72)
        self.assertEqual(items[0]["part_no"], "31392312")
        self.assertIsNone(items[0]["hs_code"])
        self.assertEqual(items[0]["quantity"], 5.0)
        self.assertEqual(items[0]["cost"], 42.63)
        self.assertEqual(items[0]["price"], 213.15)

    def test_extract_structured_pipe_items_normalizes_greek_country_code(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 132 | 8693268 | O - Ring | ΙΤ | 29 | 2,95 | 85,55 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 132)
        self.assertEqual(items[0]["part_no"], "8693268")
        self.assertEqual(items[0]["country_origin"], "IT")
        self.assertEqual(items[0]["quantity"], 29.0)
        self.assertEqual(items[0]["cost"], 2.95)
        self.assertEqual(items[0]["price"], 85.55)

    def test_extract_structured_pipe_items_normalizes_digit_distorted_country_code(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 143 | 9178540 | Gasket | E3 | 2 | 10,51 | 33,02 | 401000000 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 143)
        self.assertEqual(items[0]["part_no"], "9178540")
        self.assertEqual(items[0]["country_origin"], "ES")
        self.assertEqual(items[0]["hs_code"], "401000000")

    def test_extract_structured_pipe_items_supports_compact_no_hs_with_trailing_boilerplate(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 32 | 30653441 | Clip | SE | 50 | 1,03 | 51,50 | | | Order date: 18.06.2025 | - AVIA|"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 32)
        self.assertEqual(items[0]["part_no"], "30653441")
        self.assertIsNone(items[0]["hs_code"])
        self.assertEqual(items[0]["quantity"], 50.0)
        self.assertEqual(items[0]["cost"], 1.03)
        self.assertEqual(items[0]["price"], 51.5)

    def test_extract_structured_pipe_items_does_not_treat_description_as_country(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 43 | 30720126 | Gasket | Прокладка дроссельного узла | | 3 | 5,26 | 15,78 | 3926909709 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 43)
        self.assertEqual(items[0]["part_no"], "30720126")
        self.assertEqual(items[0]["description"], "Прокладка дроссельного узла")
        self.assertEqual(items[0]["country_origin"], "Неизвестно")

    def test_extract_structured_pipe_items_infers_quantity_for_two_value_hs_last_tail(self):
        cells = ["109", "8653857", "Valve", "Клапан EVAP", "PT", "27,35", "54,70", "8481309908"]

        item = _extract_hs_last_item(cells, 109)

        self.assertIsNotNone(item)
        self.assertEqual(item["position"], 109)
        self.assertEqual(item["quantity"], 2.0)
        self.assertEqual(item["cost"], 27.35)
        self.assertEqual(item["price"], 54.7)

    def test_extract_hs_last_item_supports_quantity_and_cost_tail(self):
        cells = [
            "216",
            "988939",
            "Screw",
            "Болт медный M8X31 Шпилька M8X58",
            "SE",
            "100 30",
            "3,65",
            "7318190008",
        ]

        item = _extract_hs_last_item(cells, 216)

        self.assertIsNotNone(item)
        self.assertEqual(item["position"], 216)
        self.assertEqual(item["quantity"], 100.0)
        self.assertEqual(item["cost"], 3.65)
        self.assertEqual(item["price"], 365.0)
        self.assertEqual(item["hs_code"], "7318190008")

    def test_extract_hs_last_item_ignores_short_trailing_suffix_after_hs(self):
        cells = [
            "135",
            "8699543",
            "Oil stick",
            "Щуп масляный двигателя D",
            "SE",
            "3",
            "16,24",
            "48,72",
            "9017801000",
            "120",
        ]

        item = _extract_hs_last_item(cells, 135)

        self.assertIsNotNone(item)
        self.assertEqual(item["position"], 135)
        self.assertEqual(item["quantity"], 3.0)
        self.assertEqual(item["cost"], 16.24)
        self.assertEqual(item["price"], 48.72)
        self.assertEqual(item["hs_code"], "9017801000")

    def test_extract_sparse_hs_item_without_country_supports_qty_cost_hs(self):
        cells = ["84", "3539879", "Clip", "Держатель", "10", "1,03", "7318159008"]

        item = _extract_sparse_hs_item_without_country(cells, 84)

        self.assertIsNotNone(item)
        self.assertEqual(item["position"], 84)
        self.assertEqual(item["quantity"], 10.0)
        self.assertEqual(item["cost"], 1.03)
        self.assertEqual(item["price"], 10.3)
        self.assertEqual(item["hs_code"], "7318159008")

    def test_extract_structured_pipe_items_supports_hs_last_single_value_rows(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 18 | 271802 | Sealing set | Прокладка коллектора выпускного | SE / | ON BOTOP | ж (8.37 Аниценой М 1 т еной сой | 146,96 | 7326909409 |\n"
            "| 117 | 8662737 | Moulding | Уплотнение крыла переднего правого | EE | ONSOTOPS OF PANEL | A 98 | 14,94 | 8708299009 |"
        )

        items = extract_structured_pipe_items(context)
        by_position = {item["position"]: item for item in items}

        self.assertEqual(len(items), 2)
        self.assertEqual(by_position[18]["part_no"], "271802")
        self.assertEqual(by_position[18]["description"], "Прокладка коллектора выпускного")
        self.assertEqual(by_position[18]["quantity"], 1.0)
        self.assertEqual(by_position[18]["cost"], 146.96)
        self.assertEqual(by_position[18]["price"], 146.96)
        self.assertEqual(by_position[18]["country_origin"], "SE")
        self.assertEqual(by_position[18]["hs_code"], "7326909409")
        self.assertEqual(by_position[117]["part_no"], "8662737")
        self.assertEqual(by_position[117]["description"], "Уплотнение крыла переднего правого")
        self.assertEqual(by_position[117]["quantity"], 1.0)
        self.assertEqual(by_position[117]["cost"], 14.94)
        self.assertEqual(by_position[117]["price"], 14.94)
        self.assertEqual(by_position[117]["country_origin"], "EE")
        self.assertEqual(by_position[117]["hs_code"], "8708299009")

    def test_extract_structured_pipe_items_salvages_shifted_tail_schema(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 509614 | EW IEM G4-TWIN-A | МОНИТОРИНГА | 00 200 | 3300 00 | "
            "МИКРОФОННАЯ СИСТЕМА ДЛЯ | 3021094145725 | Румыния | 85183090 | 4,00 | 9,13 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["position"])
        self.assertEqual(items[0]["part_no"], "509614")
        self.assertEqual(items[0]["quantity"], 4.0)
        self.assertEqual(items[0]["cost"], 825.0)
        self.assertEqual(items[0]["price"], 3300.0)
        self.assertEqual(items[0]["hs_code"], "85183090")

    def test_clean_text_trims_glued_followup_row_suffix_after_valid_item(self):
        raw_line = (
            "| 32 | 30653441 | Clip | Держатель | SE | 50 | 1,03 | 51,50 | 3926909709 | | 33 | 30656705 |"
        )

        trimmed = _trim_item_line(raw_line)
        items = extract_structured_pipe_items(f"=== INVOICE CONTENT ===\n{trimmed}")

        self.assertEqual(len(items), 1)
        self.assertEqual(trimmed, "| 32 | 30653441 | Clip | Держатель | SE | 50 | 1,03 | 51,50 | 3926909709 |")
        self.assertEqual(items[0]["position"], 32)
        self.assertEqual(items[0]["part_no"], "30653441")
        self.assertEqual(items[0]["hs_code"], "3926909709")
        self.assertEqual(items[0]["quantity"], 50.0)
        self.assertEqual(items[0]["price"], 51.5)

    def test_clean_text_trims_order_date_suffix_after_valid_item(self):
        raw_line = (
            "| 31 | 30650846 | Belt | IT | 1 | 14,26 | 14,26 | | | Order date: 24.06.2025 | - AVIA |"
        )

        trimmed = _trim_item_line(raw_line)

        self.assertEqual(trimmed, "| 31 | 30650846 | Belt | IT | 1 | 14,26 | 14,26 |")

    def test_trim_item_line_salvages_embedded_suffix_with_repeated_article_cell(self):
        raw_line = (
            "| 100 | 00000 | C | P.··· | | 2500 | | 20.40 | 7040450000 | | "
            "188 | 986066 986066 | Screw | Винт | TW | 40 | 0,76 | 30,40 | 7318159008 |"
        )

        trimmed = _trim_item_line(raw_line)
        items = extract_structured_pipe_items(f"=== INVOICE CONTENT ===\n{trimmed}")

        self.assertEqual(trimmed, "| 188 | 986066 | Screw | Винт | TW | 40 | 0,76 | 30,40 | 7318159008 |")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 188)
        self.assertEqual(items[0]["part_no"], "986066")
        self.assertEqual(items[0]["quantity"], 40.0)
        self.assertEqual(items[0]["price"], 30.4)
        self.assertEqual(items[0]["hs_code"], "7318159008")

    def test_trim_item_line_trims_glued_separator_suffix_after_hs_row(self):
        raw_line = (
            "| 31 | 30650846 | Belt | Ремень навесного оборудования B4164S3 | ΙΤ | 1 | 14,26 | 14,26 | "
            "4010390000 | ---------- | ---------------------- | ----------------------- |"
        )

        trimmed = _trim_item_line(raw_line)
        items = extract_structured_pipe_items(f"=== INVOICE CONTENT ===\n{trimmed}")

        self.assertEqual(
            trimmed,
            "| 31 | 30650846 | Belt | Ремень навесного оборудования B4164S3 | ΙΤ | 1 | 14,26 | 14,26 | 4010390000 |",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 31)
        self.assertEqual(items[0]["part_no"], "30650846")
        self.assertEqual(items[0]["hs_code"], "4010390000")
        self.assertEqual(items[0]["quantity"], 1.0)
        self.assertEqual(items[0]["cost"], 14.26)
        self.assertEqual(items[0]["price"], 14.26)

    def test_extract_structured_pipe_items_skips_order_date_shadow_rows(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 127 | 8692072 | Spark plug | Свечи зажигания | DE | 3 | 34,54 | 103,62 | 8511100009 |\n"
            "| 127 | Order date: 24.06.2025 | Spark plug - AVIA | DE | 3 | 34,54 | 103,62 |\n"
            "| 133 | 8699210 | Gasket | Прокладка EGR | SE | 2 | 8,53 | 17,06 | 7326909409 |\n"
            "| 133 | Order date: 24.06.2025 | | 3L | 2 | 6,33 | 17,00 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["description"], "Свечи зажигания")
        self.assertEqual(items[1]["description"], "Прокладка EGR")

    def test_trim_item_line_trims_short_noise_suffix_after_hs_last_row(self):
        line = "| 47 | 30731650 | Sealing ring | Сальник KB задний B63XX | TR | 2 | 15,02 | 30,04 | 4016995209 | •• | . | 0 |"

        trimmed = _trim_item_line(line)
        items = extract_structured_pipe_items(f"=== INVOICE CONTENT ===\n{trimmed}")

        self.assertEqual(
            trimmed,
            "| 47 | 30731650 | Sealing ring | Сальник KB задний B63XX | TR | 2 | 15,02 | 30,04 | 4016995209 |",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 47)
        self.assertEqual(items[0]["part_no"], "30731650")
        self.assertEqual(items[0]["hs_code"], "4016995209")

    def test_sanitize_country_origin_repairs_edge_noise_and_rejects_pseudo_codes(self):
        self.assertEqual(_sanitize_country_origin("PL X"), "PL")
        self.assertEqual(_sanitize_country_origin("i DE"), "DE")
        self.assertIsNone(_sanitize_country_origin("JE"))
        self.assertIsNone(_sanitize_country_origin("KP"))

    def test_prune_shadow_rows_drops_pos_shadows_and_positionless_fragments(self):
        items = [
            {
                "position": 988939,
                "description": "Screw",
                "hs_code": None,
                "quantity": 100.0,
                "cost": 3.78,
                "price": 378.0,
                "country_origin": "SE",
                "_line_sig": ("988939", "screw", "se", "100", "3,78", "378,00"),
            },
            {
                "position": 215,
                "description": "Screw",
                "hs_code": "7318159008",
                "quantity": 100.0,
                "cost": 3.78,
                "price": 365.0,
                "country_origin": "SE SE",
                "_line_sig": ("215", "screw", "se se", "100", "3,78", "365,00", "7318159008"),
            },
            {
                "position": 8692072,
                "description": "Свечи зажигания",
                "hs_code": "8511100009",
                "quantity": 3.0,
                "cost": 34.54,
                "price": 103.62,
                "country_origin": "DE",
                "_line_sig": ("8692072", "spark plug", "свечи зажигания", "de", "3", "34,54", "103,62", "8511100009"),
            },
            {
                "position": 8692072,
                "description": "casul atte",
                "hs_code": None,
                "quantity": 3.0,
                "cost": 24.54,
                "price": 102.62,
                "country_origin": "DE",
                "_line_sig": ("8692072", "casul atte", "de", "3", "24.54", "102.62"),
            },
            {
                "position": None,
                "description": "O Bina",
                "hs_code": "4016930005",
                "quantity": 29.0,
                "cost": 2.95,
                "price": 85.55,
                "country_origin": None,
                "_line_sig": ("000000", "o bina", "кольцо уплотнительное", "1t", "29", "2,95", "85,55", "4016930005"),
            },
        ]

        pruned = _prune_shadow_rows(items)

        self.assertEqual(len(pruned), 3)
        self.assertEqual(pruned[0]["position"], 988939)
        self.assertEqual(pruned[1]["position"], 988939)
        self.assertEqual(pruned[2]["position"], 8692072)

    def test_prune_shadow_rows_collapses_same_pos_noise_to_stronger_row(self):
        items = [
            {
                "position": 10,
                "part_no": "1306264",
                "description": "Кольцо уплотнительное трубы турбины",
                "hs_code": "4016930005",
                "quantity": 2.0,
                "cost": 1.47,
                "price": 2.94,
                "country_origin": "SE",
                "_line_sig": (
                    "10",
                    "1306264",
                    "sealing ring",
                    "кольцо уплотнительное трубы турбины",
                    "se",
                    "2",
                    "1,47",
                    "2,94",
                    "4016930005",
                ),
            },
            {
                "position": 10,
                "part_no": "1306264",
                "description": "C LIMITENMONE",
                "hs_code": "4016930005",
                "quantity": 1.0,
                "cost": 2.94,
                "price": 2.94,
                "country_origin": "SE",
                "_line_sig": (
                    "10",
                    "1306264",
                    "sealing ring",
                    "se t of week",
                    "c limitenmone",
                    "1,47",
                    "2,94",
                ),
            },
        ]

        pruned = _prune_shadow_rows(items)

        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["position"], 10)
        self.assertEqual(pruned[0]["description"], "Кольцо уплотнительное трубы турбины")

    def test_prune_shadow_rows_repairs_small_pos_rows_from_stronger_peers(self):
        items = [
            {
                "position": 986066,
                "description": "Винт",
                "hs_code": "7318159008",
                "quantity": 40.0,
                "cost": 0.76,
                "price": 30.4,
                "country_origin": "TW",
                "_line_sig": ("986066", "screw", "винт", "tw", "40", "0,76", "30,40", "7318159008"),
            },
            {
                "position": 189,
                "description": "Винт",
                "hs_code": "7318159008",
                "quantity": 10.0,
                "cost": 0.76,
                "price": 7.6,
                "country_origin": "TW",
                "_line_sig": ("189", "screw", "винт", "tw", "10", "0,76", "7,60", "7318159008"),
            },
            {
                "position": 8699210,
                "description": "Прокладка EGR",
                "hs_code": "7326909409",
                "quantity": 2.0,
                "cost": 8.53,
                "price": 17.06,
                "country_origin": "SE",
                "_line_sig": ("8699210", "gasket", "прокладка egr", "se", "2", "8,53", "17,06", "7326909409"),
            },
            {
                "position": 134,
                "description": "Gasket",
                "hs_code": None,
                "quantity": 2.0,
                "cost": 8.53,
                "price": 17.06,
                "country_origin": "SE",
                "_line_sig": ("134", "gasket", "se", "2", "8,53", "17,06"),
            },
            {
                "position": 103,
                "description": "710my 1 00mm = -1-1",
                "hs_code": "2047220000",
                "quantity": 10.0,
                "cost": 4.22,
                "price": 42.2,
                "country_origin": None,
                "_line_sig": ("103", "j70301", "nose clomp", "710my 1 00mm = -1-1", "termovoariva", "40", "4 22", "42.20", "2047220000"),
            },
        ]

        pruned = _prune_shadow_rows(items)
        positions = [item["position"] for item in pruned]

        self.assertNotIn(103, positions)
        self.assertNotIn(134, positions)
        self.assertNotIn(189, positions)
        self.assertEqual(sum(1 for item in pruned if item["position"] == 986066), 2)
        self.assertEqual(sum(1 for item in pruned if item["position"] == 8699210), 2)

    def test_prune_shadow_rows_keeps_positionless_cyrillic_item(self):
        items = [
            {
                "position": None,
                "description": "МИКРОФОН",
                "hs_code": "85181090",
                "quantity": 11.0,
                "cost": 110.0,
                "price": 1210.0,
                "country_origin": "Германия",
                "_line_sig": ("0", "mmd 945-1 bk", "микрофон", "германия", "85181090", "11,00", "110,00", "1210,00"),
            }
        ]

        pruned = _prune_shadow_rows(items)

        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["description"], "МИКРОФОН")

    def test_prune_shadow_rows_drops_proportional_translation_shadow(self):
        items = [
            {
                "position": 31693070,
                "description": "КОМПЛЕКТ ДРМ ДВЕР",
                "hs_code": "8302300009",
                "quantity": 1.0,
                "cost": 15.22,
                "price": 15.22,
                "country_origin": "SE",
            },
            {
                "position": 31693070,
                "description": "Building kit",
                "hs_code": "8302300009",
                "quantity": 13.0,
                "cost": 1.1708,
                "price": 15.22,
                "country_origin": "SE",
            },
        ]

        pruned = _prune_shadow_rows(items)

        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["description"], "КОМПЛЕКТ ДРМ ДВЕР")

    def test_prune_shadow_rows_drops_one_digit_article_shadow_without_hs(self):
        items = [
            {
                "position": 9484616,
                "description": "Крышка поводка очистителя",
                "hs_code": "3926909709",
                "quantity": 10.0,
                "cost": 9.43,
                "price": 94.3,
                "country_origin": "SK",
            },
            {
                "position": 9464616,
                "description": "сар",
                "hs_code": None,
                "quantity": 10.0,
                "cost": 3.15,
                "price": 31.5,
                "country_origin": "SK",
            },
        ]

        pruned = _prune_shadow_rows(items)

        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["position"], 9484616)

    def test_normalize_invoice_items_backfills_country_from_numeric_code_and_harmonizes_hs(self):
        items = [
            {
                "position": 986061,
                "description": "Винт 5,0х14 мм шестигранный",
                "hs_code": "1210122000",
                "quantity": 10.0,
                "cost": 0.76,
                "price": 7.6,
                "country_origin": "DE",
            },
            {
                "position": 986061,
                "description": "Винт 5,0х14 мм шестигранный",
                "hs_code": "7318159008",
                "quantity": 4.0,
                "cost": 0.76,
                "price": 3.04,
                "country_origin": "IDE",
            },
            {
                "position": 986087,
                "description": "Винт",
                "hs_code": "7318159008",
                "quantity": 10.0,
                "cost": 0.76,
                "price": 7.6,
                "country_origin": "DE",
            },
            {
                "position": 9484616,
                "description": "Крышка поводка очистителя",
                "hs_code": "3926909709",
                "quantity": 10.0,
                "cost": 9.43,
                "price": 94.3,
                "country_origin": None,
                "country_origin_code": 703,
            },
        ]

        normalized = normalize_invoice_items(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )
        rows_986061 = [item for item in normalized if item["position"] in {986061, 986062}]
        rows_9484616 = [item for item in normalized if item["position"] == 9484616]

        self.assertEqual(len(rows_986061), 2)
        self.assertTrue(all(row["hs_code"] == "7318159008" for row in rows_986061))
        self.assertTrue(all(row["country_origin"] == "Германия" for row in rows_986061))
        self.assertEqual(len(rows_9484616), 1)
        self.assertEqual(rows_9484616[0]["country_origin"], "Словакия")

    def test_normalize_invoice_items_annotates_low_confidence_rows(self):
        items = [
            {
                "position": 8653344,
                "description": "картерных газов",
                "hs_code": None,
                "quantity": 4.0,
                "unit": "pcs",
                "cost": 18.83,
                "price": 75.32,
                "country_origin": None,
            },
            {
                "position": 985324,
                "description": "Болт фланцевый",
                "hs_code": None,
                "quantity": 2.0,
                "unit": "pcs",
                "cost": 3.96,
                "price": 7.92,
                "country_origin": "NL",
            },
            {
                "position": 1234567,
                "description": "Valve",
                "hs_code": "8481309908",
                "quantity": 2.0,
                "unit": "pcs",
                "cost": 27.35,
                "price": 54.70,
                "country_origin": "PT",
                "_peer_hydrated": True,
            },
            {
                "position": 30731650,
                "description": "Сальник KB задний B63XX",
                "hs_code": "4016995209",
                "quantity": 2.0,
                "unit": "pcs",
                "cost": 15.02,
                "price": 30.04,
                "country_origin": "TR",
            },
        ]

        normalized = normalize_invoice_items(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows = {item["position"]: item for item in normalized}
        self.assertEqual(rows[8653344]["parsing_confidence"], "low")
        self.assertTrue(rows[8653344]["review_required"])
        self.assertEqual(rows[8653344]["review_priority"], "high")
        self.assertEqual(rows[8653344]["review_reason_count"], 2)
        self.assertIn("missing_hs_code", rows[8653344]["review_notes"])
        self.assertIn("missing_country_origin", rows[8653344]["review_notes"])
        self.assertEqual(rows[985324]["parsing_confidence"], "medium")
        self.assertTrue(rows[985324]["review_required"])
        self.assertEqual(rows[985324]["review_priority"], "high")
        self.assertEqual(rows[985324]["review_reason_count"], 1)
        self.assertEqual(rows[1234567]["parsing_confidence"], "medium")
        self.assertTrue(rows[1234567]["review_required"])
        self.assertEqual(rows[1234567]["review_priority"], "medium")
        self.assertEqual(rows[1234567]["review_reason_count"], 1)
        self.assertIn("peer_repaired", rows[1234567]["review_notes"])
        self.assertEqual(rows[30731650]["parsing_confidence"], "high")
        self.assertFalse(rows[30731650]["review_required"])
        self.assertEqual(rows[30731650]["review_priority"], "none")
        self.assertEqual(rows[30731650]["review_reason_count"], 0)

    def test_normalize_invoice_items_supports_lightweight_assessment_mode(self):
        items = [
            {
                "position": 8653344,
                "description": "Hose картерных газов",
                "hs_code": None,
                "quantity": 4.0,
                "unit": "pcs",
                "cost": 18.83,
                "price": 75.32,
                "country_origin": None,
                "_line_sig": ("108", "8653344", "hose", "картерных газов", "4", "18,83", "75,32"),
            }
        ]

        normalized = normalize_invoice_items(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
            annotate_review=False,
            strip_internal_fields=False,
            sort_output=False,
        )

        self.assertEqual(len(normalized), 1)
        self.assertNotIn("parsing_confidence", normalized[0])
        self.assertNotIn("review_required", normalized[0])
        self.assertIn("_line_sig", normalized[0])
        self.assertEqual(normalized[0]["country_origin"], None)

    def test_prepare_invoice_items_for_merge_keeps_internal_fields_for_assist_merge(self):
        items = [
            {
                "position": 600001,
                "description": "Widget Pro",
                "hs_code": "85181090",
                "quantity": 6.0,
                "unit": "pcs",
                "cost": 55.0,
                "price": 330.0,
                "country_origin": "Germany",
                "_line_sig": ("600001", "widget pro"),
            }
        ]

        prepared = prepare_invoice_items_for_merge(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
        )

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["document_number"], "206447")
        self.assertEqual(prepared[0]["currency_code"], "EUR")
        self.assertIn("_line_sig", prepared[0])
        self.assertNotIn("review_required", prepared[0])

    def test_normalize_invoice_items_hydrates_partial_hs_companions(self):
        items = [
            {
                "position": 8688207,
                "description": "Корпус разъема",
                "hs_code": "8536699008",
                "quantity": 4.0,
                "unit": "pcs",
                "cost": None,
                "price": None,
                "country_origin": None,
                "_peer_hydrated": True,
                "_line_sig": ("8688207", "plug", "корпус разъема", "4", "8536699008"),
            },
            {
                "position": 8688207,
                "description": "Корпус разъема",
                "hs_code": None,
                "quantity": 5.0,
                "unit": "pcs",
                "cost": 2.9,
                "price": 14.5,
                "country_origin": "BE",
                "_line_sig": ("8688207", "plug", "корпус разъема", "be", "5", "2,90", "14,50"),
            },
            {
                "position": 8693268,
                "description": "O - Ring",
                "hs_code": None,
                "quantity": 29.0,
                "unit": "pcs",
                "cost": 2.95,
                "price": 85.55,
                "country_origin": "IT",
                "_line_sig": ("8693268", "o - ring", "it", "29", "2,95", "85,55"),
            },
            {
                "position": 8693268,
                "description": "O - Ring",
                "hs_code": "7326909409",
                "quantity": None,
                "unit": "pcs",
                "cost": None,
                "price": None,
                "country_origin": None,
                "_peer_hydrated": True,
                "_line_sig": ("8693268", "o - ring", "7326909409"),
            },
            {
                "position": 9123867,
                "description": "Вал",
                "hs_code": None,
                "quantity": 1.0,
                "unit": "pcs",
                "cost": 22.98,
                "price": 22.98,
                "country_origin": "DE",
                "_line_sig": ("9123867", "shaft", "вал", "de", "1", "22,98", "22,98"),
            },
            {
                "position": 9123867,
                "description": "Shaft",
                "hs_code": "8483109500",
                "quantity": None,
                "unit": "pcs",
                "cost": None,
                "price": None,
                "country_origin": None,
                "_peer_hydrated": True,
                "_line_sig": ("9123867", "shaft", "8483109500"),
            },
            {
                "position": 30731377,
                "description": "Кольцо уплотнительное инжектора (к-т на 1 форсунку)",
                "hs_code": None,
                "quantity": 1.0,
                "unit": "pcs",
                "cost": 7.67,
                "price": 7.67,
                "country_origin": "JP",
                "_decl_ref": "4016930005",
                "_line_sig": ("30731377", "o-ring", "jp", "1", "7,67", "7,67", "40.16930005"),
            },
        ]

        normalized = normalize_invoice_items(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows_8688207 = [item for item in normalized if item["position"] in {8688207, 8688208}]
        rows_8693268 = [item for item in normalized if item["position"] == 8693268]
        rows_9123867 = [item for item in normalized if item["position"] == 9123867]
        rows_30731377 = [item for item in normalized if item["position"] == 30731377]

        self.assertEqual(len(rows_8688207), 2)
        self.assertEqual({row["quantity"] for row in rows_8688207}, {4.0, 5.0})
        self.assertTrue(all(row["hs_code"] == "8536699008" for row in rows_8688207))
        self.assertTrue(all(row["country_origin"] == "Бельгия" for row in rows_8688207))
        qty4_row = next(row for row in rows_8688207 if row["quantity"] == 4.0)
        self.assertEqual(qty4_row["cost"], 2.9)
        self.assertEqual(qty4_row["price"], 11.6)

        self.assertEqual(len(rows_8693268), 1)
        self.assertEqual(rows_8693268[0]["hs_code"], "7326909409")
        self.assertEqual(rows_8693268[0]["country_origin"], "Италия")

        self.assertEqual(len(rows_9123867), 1)
        self.assertEqual(rows_9123867[0]["hs_code"], "8483109500")

        self.assertEqual(len(rows_30731377), 1)
        self.assertEqual(rows_30731377[0]["hs_code"], "4016930005")

    def test_normalize_invoice_items_promotes_marker_positionless_companion(self):
        items = extract_structured_pipe_items(
            "=== INVOICE CONTENT ===\n"
            "| | | * | Уплотнитель стекла фары, | ES | 2 | 16,51 | 33,02 | 4016930005 |\n"
            "| 143 | 9178540 | Gasket | E3 | 2 | 10,51 | 33,02 | 401000000 |\n"
        )

        normalized = normalize_invoice_items(
            items,
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows_9178540 = [item for item in normalized if item["position"] == 143]

        self.assertEqual(len(rows_9178540), 1)
        self.assertEqual(rows_9178540[0]["part_no"], "9178540")
        self.assertEqual(rows_9178540[0]["description"], "Уплотнитель стекла фары,")
        self.assertEqual(rows_9178540[0]["country_origin"], "Испания")
        self.assertEqual(rows_9178540[0]["quantity"], 2.0)
        self.assertEqual(rows_9178540[0]["cost"], 16.51)
        self.assertEqual(rows_9178540[0]["price"], 33.02)
        self.assertEqual(rows_9178540[0]["hs_code"], "4016930005")

    def test_normalize_invoice_items_hydrates_missing_hs_from_close_peer_description(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 30736724,
                    "description": "Проставка под пружину (зад подвеска)",
                    "hs_code": "4016995709",
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 12.4,
                    "price": 12.4,
                    "country_origin": "DE",
                    "_line_sig": (
                        "30736724",
                        "washer",
                        "проставка под пружину зад подвеска",
                        "de",
                        "1",
                        "12,40",
                        "12,40",
                        "4016995709",
                    ),
                },
                {
                    "position": 30736724,
                    "description": "Проставка под пружину (зад",
                    "hs_code": None,
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 12.4,
                    "price": 12.4,
                    "country_origin": None,
                    "_line_sig": (
                        "30736724",
                        "washer",
                        "проставка под пружину зад",
                        "1",
                        "12,40",
                        "12,40",
                    ),
                },
            ],
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows = [item for item in normalized if item["position"] == 30736724]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hs_code"], "4016995709")
        self.assertEqual(rows[0]["country_origin"], "Германия")

    def test_normalize_invoice_items_prefers_cyrillic_peer_description_for_same_numeric_signature(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 30713459,
                    "description": "Valve cover gasket",
                    "hs_code": None,
                    "quantity": 16.0,
                    "unit": "pcs",
                    "cost": 26.54,
                    "price": 424.64,
                    "country_origin": None,
                    "_line_sig": ("30713459", "valve cover gasket", "16", "26,54", "424,64"),
                },
                {
                    "position": 30713459,
                    "description": "Прокладка впускного коллектора (кл.крышки)",
                    "hs_code": "4016930005",
                    "quantity": 16.0,
                    "unit": "pcs",
                    "cost": 26.54,
                    "price": 424.64,
                    "country_origin": "DE",
                    "_line_sig": (
                        "30713459",
                        "valve cover gasket",
                        "прокладка впускного коллектора",
                        "de",
                        "16",
                        "26,54",
                        "424,64",
                        "4016930005",
                    ),
                },
            ],
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows = [item for item in normalized if item["position"] == 30713459]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Прокладка впускного коллектора (кл.крышки)")
        self.assertEqual(rows[0]["hs_code"], "4016930005")
        self.assertEqual(rows[0]["country_origin"], "Германия")

    def test_normalize_invoice_items_prefers_richer_cyrillic_peer_for_mixed_description(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 8653344,
                    "description": "Hose картерных газов",
                    "hs_code": None,
                    "quantity": 4.0,
                    "unit": "pcs",
                    "cost": 18.83,
                    "price": 75.32,
                    "country_origin": None,
                    "_line_sig": ("8653344", "hose", "картерных газов", "4", "18,83", "75,32"),
                },
                {
                    "position": 8653344,
                    "description": "Трубка рециркуляции картерных газов",
                    "hs_code": "4009110000",
                    "quantity": 4.0,
                    "unit": "pcs",
                    "cost": 18.83,
                    "price": 75.32,
                    "country_origin": "SE",
                    "_line_sig": (
                        "8653344",
                        "hose",
                        "трубка рециркуляции картерных газов",
                        "se",
                        "4",
                        "18,83",
                        "75,32",
                        "4009110000",
                    ),
                },
            ],
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows = [item for item in normalized if item["position"] == 8653344]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Трубка рециркуляции картерных газов")
        self.assertEqual(rows[0]["hs_code"], "4009110000")
        self.assertEqual(rows[0]["country_origin"], "Швеция")

    def test_normalize_invoice_items_preserves_distinct_same_value_rows_with_exact_line_sigs(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 30736724,
                    "description": "Проставка под пружину (зад",
                    "hs_code": "4016995709",
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 12.4,
                    "price": 12.4,
                    "country_origin": "DE",
                    "_decl_ref": "4016995709",
                    "_line_sig": ("30736724", "washer", "проставка под пружину (зад", "de", "1", "12,40", "12,40", "4016995 7 09"),
                },
                {
                    "position": 30736724,
                    "description": "Проставка под пружину (зад подвеска)",
                    "hs_code": None,
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 12.4,
                    "price": 12.4,
                    "country_origin": "DE",
                    "_line_sig": ("30736724", "washer", "проставка под пружину (зад подвеска)", "de", "1", "12,40", "12,40"),
                },
            ],
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        rows_30736724 = [item for item in normalized if item["position"] == 30736724]

        self.assertEqual(len(rows_30736724), 1)
        self.assertEqual(rows_30736724[0]["hs_code"], "4016995709")
        self.assertEqual(rows_30736724[0]["description"], "Проставка под пружину (зад подвеска)")

    def test_normalize_invoice_items_reconciles_noisy_quantity_from_total(self):
        normalized = normalize_invoice_items(
            [
                {
                    "position": 30640776,
                    "description": "Хомут-зажим 18,5 мм",
                    "hs_code": "7326909807",
                    "quantity": 39.0,
                    "unit": "pcs",
                    "cost": 1.92,
                    "price": 57.6,
                    "country_origin": "DE",
                }
            ],
            {"document_number": "206447", "document_date": "21.07.2025", "currency_code": "EUR"},
            [],
            preserve_exact_line_duplicates=True,
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["quantity"], 30.0)
        self.assertEqual(normalized[0]["price"], 57.6)

    def test_build_header_metadata_parses_invoice_number_date_and_currency(self):
        context = (
            "=== CURRENCY DATABASE (REFERENCE) ===\n[]\n\n"
            "=== INVOICE CONTENT ===\n"
            "G.S. Autoteile GmbH Invoice Page: 1/15 21.07.2025 Date: Invoice Number: 206447\n"
            "Total Amount (EUR): 34.839,63\n"
            "| 1 | 1161748 | Grease | SE | 20 | 8,82 | 176,40 | 3403990000 |"
        )

        _header_context, header_meta = build_header_metadata(context)

        self.assertEqual(header_meta["document_number"], "206447")
        self.assertEqual(header_meta["document_date"], "21.07.2025")
        self.assertEqual(header_meta["currency_code"], "EUR")

    def test_invoice_handler_populates_table_fields_from_items(self):
        handler = InvoiceHandler()

        with patch(
            "extractor.documents.invoice.invoice.run_invoice_extraction",
            return_value={
                "result": {
                    "items": [
                        {
                            "position": 1161748,
                            "description": "Grease",
                            "document_number": "206447",
                            "document_date": "21.07.2025",
                            "currency_code": "EUR",
                            "currency_name": "Euro",
                        }
                    ],
                    "count": 1,
                },
                "metrics": {},
                "model_id": "structured-parser",
            },
        ):
            result = handler.extract(ocr_draft="stub")

        self.assertEqual(
            result["data"]["fields"],
            {
                "document_number": "206447",
                "document_date": "21.07.2025",
                "currency_code": "EUR",
                "currency_name": "Euro",
                "country_sender": None,
            },
        )

    def test_invoice_handler_builds_review_summary(self):
        handler = InvoiceHandler()

        with patch(
            "extractor.documents.invoice.invoice.run_invoice_extraction",
            return_value={
                "result": {
                    "items": [
                        {
                            "position": 8653344,
                            "description": "Hose картерных газов",
                            "review_required": True,
                            "review_priority": "high",
                            "review_reason_count": 2,
                            "review_notes": "missing_hs_code, missing_country_origin",
                        },
                        {
                            "position": 985324,
                            "description": "Болт фланцевый",
                            "review_required": True,
                            "review_priority": "high",
                            "review_reason_count": 1,
                            "review_notes": "missing_hs_code",
                        },
                        {
                            "position": 1234567,
                            "description": "Valve",
                            "review_required": True,
                            "review_priority": "medium",
                            "review_reason_count": 1,
                            "review_notes": "peer_repaired",
                        },
                        {
                            "position": 30731650,
                            "description": "Сальник KB задний B63XX",
                            "review_required": False,
                            "review_priority": "none",
                            "review_reason_count": 0,
                            "review_notes": None,
                        },
                    ],
                    "count": 4,
                },
                "metrics": {},
                "model_id": "structured-parser",
            },
        ):
            result = handler.extract(ocr_draft="stub")

        self.assertEqual(
            result["data"]["review_summary"],
            {
                "review_required_count": 3,
                "high_priority_count": 2,
                "medium_priority_count": 1,
                "positions": [985324, 1234567, 8653344],
                "high_priority_positions": [985324, 8653344],
                "medium_priority_positions": [1234567],
            },
        )

    def test_invoice_handler_builds_top_review_items(self):
        handler = InvoiceHandler()

        with patch(
            "extractor.documents.invoice.invoice.run_invoice_extraction",
            return_value={
                "result": {
                    "items": [
                        {
                            "position": 30731650,
                            "description": "Сальник KB задний B63XX",
                            "review_required": False,
                            "review_priority": "none",
                            "review_reason_count": 0,
                            "review_notes": None,
                            "parsing_confidence": "high",
                        },
                        {
                            "position": 8653344,
                            "description": "Hose картерных газов",
                            "review_required": True,
                            "review_priority": "high",
                            "review_reason_count": 2,
                            "review_notes": "missing_hs_code, missing_country_origin",
                            "parsing_confidence": "low",
                        },
                        {
                            "position": 985324,
                            "description": "Болт фланцевый",
                            "review_required": True,
                            "review_priority": "high",
                            "review_reason_count": 1,
                            "review_notes": "missing_hs_code",
                            "parsing_confidence": "medium",
                        },
                        {
                            "position": 1234567,
                            "description": "Valve",
                            "review_required": True,
                            "review_priority": "medium",
                            "review_reason_count": 1,
                            "review_notes": "peer_repaired",
                            "parsing_confidence": "medium",
                        },
                    ],
                    "count": 4,
                },
                "metrics": {},
                "model_id": "structured-parser",
            },
        ):
            result = handler.extract(ocr_draft="stub")

        self.assertEqual(
            result["data"]["top_review_items"],
            [
                {
                    "position": 8653344,
                    "description": "Hose картерных газов",
                    "review_priority": "high",
                    "review_reason_count": 2,
                    "review_notes": "missing_hs_code, missing_country_origin",
                    "review_label": "Missing HS code + Missing country",
                    "parsing_confidence": "low",
                },
                {
                    "position": 985324,
                    "description": "Болт фланцевый",
                    "review_priority": "high",
                    "review_reason_count": 1,
                    "review_notes": "missing_hs_code",
                    "review_label": "Missing HS code",
                    "parsing_confidence": "medium",
                },
                {
                    "position": 1234567,
                    "description": "Valve",
                    "review_priority": "medium",
                    "review_reason_count": 1,
                    "review_notes": "peer_repaired",
                    "review_label": "Peer repaired",
                    "parsing_confidence": "medium",
                },
            ],
        )

    def test_extract_structured_pipe_items_keeps_valid_row_with_zero_position(self):
        context = (
            "=== INVOICE CONTENT ===\n"
            "| 0 | MMD 945-1 BK | МИКРОФОН | 3021065037825 | Германия | "
            "85181090 | 11,00 | 1,76 | 5,79 | 110,00 | 1210,00 |"
        )

        items = extract_structured_pipe_items(context)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["position"])
        self.assertEqual(items[0]["price"], 1210.0)

    @patch("extractor.documents.invoice.invoice._extract_with_timing")
    @patch(
        "extractor.documents.invoice.invoice.load_currency_db",
        return_value=[{"code": "USD", "name": "US Dollar"}],
    )
    def test_run_invoice_extraction_short_circuits_to_structured_parser(
        self,
        _mock_load_currency_db,
        mock_extract_with_timing,
    ):
        raw_text = "\n".join(
            [
                "Invoice Number: 000223420",
                "Currency: USD",
                *[
                    (
                        f"| {507100 + idx} | XSW ITEM {idx} | МИКРОФОН | 3021118073325 | Тайвань | "
                        f"85181090 | 4,00 | 2,00 | 3,46 | 192,50 | 770,00 |"
                    )
                    for idx in range(18)
                ],
            ]
        )

        result = run_invoice_extraction(raw_text, model_id="cerebras")

        mock_extract_with_timing.assert_not_called()
        self.assertEqual(result["model_id"], "structured-parser")
        self.assertEqual(result["result"]["count"], 18)
        self.assertEqual(result["metrics"]["execution_path"]["mode"], "parser_first")
        self.assertTrue(result["metrics"]["primary_valid"])

    @patch("extractor.documents.invoice.invoice._extract_with_timing")
    @patch(
        "extractor.documents.invoice.invoice.load_currency_db",
        return_value=[{"code": "USD", "name": "US Dollar"}],
    )
    def test_run_invoice_extraction_short_circuits_on_duplicate_heavy_table_ocr(
        self,
        _mock_load_currency_db,
        mock_extract_with_timing,
    ):
        item_rows = [
            (
                f"| {507100 + idx} | XSW ITEM {idx} | МИКРОФОН | 3021118073325 | Тайвань | "
                f"85181090 | 4,00 | 2,00 | 3,46 | 192,50 | 770,00 |"
            )
            for idx in range(18)
        ]
        raw_text = "\n".join(
            [
                "Invoice Number: 000223420",
                "Currency: USD",
                *item_rows,
                "Page 2 repeat",
                *item_rows,
                "Page 3 repeat",
                *item_rows,
            ]
        )

        result = run_invoice_extraction(raw_text, model_id="cerebras")

        mock_extract_with_timing.assert_not_called()
        self.assertEqual(result["model_id"], "structured-parser")
        self.assertEqual(result["result"]["count"], 18)
        assessment = result["metrics"]["execution_path"]["structured_parser"]
        self.assertEqual(result["metrics"]["execution_path"]["mode"], "parser_first")
        self.assertEqual(assessment["candidate_rows"], 18)
        self.assertEqual(assessment["candidate_rows_raw"], 54)
        self.assertGreaterEqual(assessment["duplicate_inflation_ratio"], 3.0)

    @patch("extractor.documents.invoice.invoice._extract_with_timing")
    @patch(
        "extractor.documents.invoice.invoice.load_currency_db",
        return_value=[{"code": "USD", "name": "US Dollar"}],
    )
    def test_run_invoice_extraction_supports_hs_at_end_table_schema(
        self,
        _mock_load_currency_db,
        mock_extract_with_timing,
    ):
        raw_text = "\n".join(
            [
                "Invoice Number: 206447",
                "Currency: EUR",
                *[
                    (
                        f"| {idx} | {3000000 + idx} | Grease | Смазка для узла {idx} | SE | "
                        f"{idx + 1} | 8,82 | {round((idx + 1) * 8.82, 2):.2f} | 3403990000 |"
                    ).replace(".", ",", 1)
                    for idx in range(1, 21)
                ],
            ]
        )

        result = run_invoice_extraction(raw_text, model_id="cerebras")

        mock_extract_with_timing.assert_not_called()
        self.assertEqual(result["model_id"], "structured-parser")
        self.assertEqual(result["result"]["count"], 20)
        self.assertEqual(result["result"]["items"][0]["hs_code"], "3403990000")
        self.assertIn("Смазка", result["result"]["items"][0]["description"])

    @patch("extractor.documents.invoice.invoice._extract_with_timing")
    @patch(
        "extractor.documents.invoice.invoice.load_currency_db",
        return_value=[{"code": "USD", "name": "US Dollar"}],
    )
    def test_run_invoice_extraction_uses_selective_llm_assist_for_unparsed_rows(
        self,
        _mock_load_currency_db,
        mock_extract_with_timing,
    ):
        good_rows = [
            (
                f"| {507100 + idx} | XSW ITEM {idx} | МИКРОФОН | 3021118073325 | Тайвань | "
                f"85181090 | 4,00 | 2,00 | 3,46 | 192,50 | 770,00 |"
            )
            for idx in range(18)
        ]
        unresolved_line = (
            "| 600001 | WIDGET PRO | МИКРОФОН | 3021118073325 | Германия | "
            "BROKEN | ??? | 55,00 | ??? |"
        )
        raw_text = "\n".join(
            [
                "Invoice Number: 000223420",
                "Currency: USD",
                *good_rows,
                unresolved_line,
            ]
        )

        assist_item = {
            "position": 600001,
            "description": "Widget Pro",
            "hs_code": "85181090",
            "quantity": 6.0,
            "unit": "pcs",
            "cost": 55.0,
            "price": 330.0,
            "country_origin": "Germany",
        }
        mock_extract_with_timing.return_value = {
            "raw_output": '{"items":[{"position":600001,"description":"Widget Pro","hs_code":"85181090","quantity":6,"unit":"pcs","cost":55,"price":330,"country_origin":"Germany"}]}',
            "annotated_doc": None,
            "usage": {"total_tokens": 100},
            "validation": {"is_valid": 1, "data": {"items": [assist_item], "count": 1}, "error": ""},
            "llm_seconds": 0.01,
            "validate_seconds": 0.0,
        }

        result = run_invoice_extraction(raw_text, model_id="gemini-flash")

        self.assertEqual(mock_extract_with_timing.call_count, 1)
        self.assertEqual(result["model_id"], "structured-parser")
        self.assertEqual(result["result"]["count"], 19)
        self.assertEqual(result["metrics"]["execution_path"]["mode"], "parser_first")
        assist = result["metrics"]["execution_path"]["assist"]
        self.assertEqual(assist["candidate_lines"], 1)
        self.assertEqual(assist["repaired_items"], 1)
        self.assertTrue(assist["used"])
        self.assertEqual(assist["model_id"], "gemini-2.5-flash")
        repaired = [item for item in result["result"]["items"] if item.get("description") == "Widget Pro"]
        self.assertEqual(len(repaired), 1)

    @patch("extractor.documents.invoice.invoice.run_line_level_llm_assist")
    @patch("extractor.documents.invoice.invoice._collect_line_level_repair_candidates")
    @patch("extractor.documents.invoice.invoice.merge_normalized_invoice_items")
    @patch("extractor.documents.invoice.invoice.normalize_invoice_items")
    @patch("extractor.documents.invoice.invoice._assess_structured_parser")
    @patch("extractor.documents.invoice.invoice.extract_structured_pipe_items")
    @patch("extractor.documents.invoice.invoice._build_header_metadata")
    @patch("extractor.documents.invoice.invoice.clean_text")
    @patch(
        "extractor.documents.invoice.invoice.load_currency_db",
        return_value=[{"code": "USD", "name": "US Dollar"}],
    )
    def test_run_invoice_extraction_discards_assist_when_merge_reduces_count(
        self,
        _mock_load_currency_db,
        mock_clean_text,
        mock_build_header_metadata,
        mock_extract_structured_pipe_items,
        mock_assess_structured_parser,
        mock_normalize_invoice_items,
        mock_merge_normalized_invoice_items,
        mock_collect_line_level_repair_candidates,
        mock_run_line_level_llm_assist,
    ):
        base_items = [
            {
                "position": 101,
                "description": "Item A",
                "hs_code": "85181090",
                "quantity": 1.0,
                "unit": "pcs",
                "cost": 10.0,
                "price": 10.0,
                "country_origin": "DE",
                "_line_sig": ("101", "item a"),
            },
            {
                "position": 102,
                "description": "Item B",
                "hs_code": "85181090",
                "quantity": 1.0,
                "unit": "pcs",
                "cost": 20.0,
                "price": 20.0,
                "country_origin": "DE",
                "_line_sig": ("102", "item b"),
            },
        ]
        reduced_items = [base_items[0]]

        mock_clean_text.return_value = "ctx"
        mock_build_header_metadata.return_value = ("header", {})
        mock_extract_structured_pipe_items.return_value = list(base_items)
        mock_collect_line_level_repair_candidates.return_value = ["broken line"]
        mock_assess_structured_parser.return_value = {
            "use_parser_first": True,
            "candidate_rows": 2,
            "candidate_rows_raw": 2,
            "parsed_items": 2,
            "unique_positions": 2,
            "coverage_ratio": 1.0,
            "completeness_ratio": 1.0,
            "duplicate_inflation_ratio": 1.0,
        }
        mock_normalize_invoice_items.side_effect = [
            list(base_items),
            list(base_items),
        ]
        mock_merge_normalized_invoice_items.return_value = list(reduced_items)
        mock_run_line_level_llm_assist.return_value = {
            "items": [
                {
                    "position": 999,
                    "description": "Bad assist row",
                    "hs_code": "85181090",
                    "quantity": 1.0,
                    "unit": "pcs",
                    "cost": 1.0,
                    "price": 1.0,
                    "country_origin": "DE",
                }
            ],
            "raw_output": "[]",
            "annotated_doc": None,
            "usage": {},
            "fallback_used": False,
            "model_id": "gemini-2.5-flash",
            "valid": True,
        }

        result = run_invoice_extraction("raw invoice", model_id="gemini-flash")

        self.assertEqual(result["result"]["count"], 2)
        assist = result["metrics"]["execution_path"]["assist"]
        self.assertFalse(assist["used"])
        self.assertTrue(assist["discarded"])
        self.assertEqual(assist["discard_reason"], "reduced_parser_count")
