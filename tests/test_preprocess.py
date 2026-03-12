import unittest

from extractor.preprocess import clean_text


class CleanTextTests(unittest.TestCase):
    def test_clean_text_compacts_pipe_table_ocr_noise(self):
        raw_text = """
Invoice Number: 000223420
Invoice Number: 000223420
Currency: USD
Currency: USD
| Part No | Description | Origin | Qty | Price | Total |
| 506992 | XSW 1-ME3-GB | TW | 4,00 | 220,00 | 880,00 |
| 507115 | XSW 1-835-A | TW | 4,00 | 192,50 | 770,00 |
| + | 507122 | XSW 2-ME2-A | TW | 3,00 | 264,00 | 792,00 |
| 507129 | XSW 2-ME3-A | TW | 3,00 | 275,00 | 825,00 |
| 507130 | XSW 2-ME3-B | TW | 7,00 | 275,00 | 1925,00 |
| 507143 | XSW 2-835-A | TW | 15,00 | 247,50 | 3712,50 |
| 507150 | XSW 2-865-A | TW | 3,00 | 275,00 | 825,00 |
| 507151 | XSW 2-865-B | TW | 1,00 | 275,00 | 275,00 |
Обци Обци Обци Обци Обци Обци Обци Обци 1000 1000 1000 1000 1000 1000 1000 1000
"""
        cleaned = clean_text(raw_text, '[{"code":"USD","name":"US Dollar"}]')

        self.assertEqual(cleaned.count("Invoice Number: 000223420"), 1)
        self.assertEqual(cleaned.count("Currency: USD"), 1)
        self.assertIn("| 506992 | XSW 1-ME3-GB | TW | 4,00 | 220,00 | 880,00 |", cleaned)
        self.assertIn("| 507122 | XSW 2-ME2-A | TW | 3,00 | 264,00 | 792,00 |", cleaned)
        self.assertNotIn("| + | 507122 |", cleaned)
        self.assertNotIn("Обци Обци Обци", cleaned)

    def test_clean_text_does_not_overfilter_non_table_ocr(self):
        raw_text = """
Commercial invoice
Invoice Number: INV-001
Description: Studio microphone
Country of destination: Kyrgyzstan
"""
        cleaned = clean_text(raw_text, '[{"code":"USD","name":"US Dollar"}]')

        self.assertIn("Commercial invoice", cleaned)
        self.assertIn("Invoice Number: INV-001", cleaned)
        self.assertIn("Description: Studio microphone", cleaned)

