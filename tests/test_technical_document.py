import unittest

from extractor.documents.regular.technical_document import (
    TechnicalDocumentHandler,
    validate_technical_document_response,
)


class TechnicalDocumentTests(unittest.TestCase):
    def test_short_non_json_response_is_invalid(self) -> None:
        is_valid, _, items = validate_technical_document_response("I cannot help with that.")
        self.assertFalse(is_valid)
        self.assertEqual(items, [])

    def test_missing_date_is_not_replaced_with_today(self) -> None:
        handler = TechnicalDocumentHandler()
        self.assertIsNone(handler._normalize_date(None))
        self.assertIsNone(handler._normalize_date("NO_DATE_FOUND"))


if __name__ == "__main__":
    unittest.main()
