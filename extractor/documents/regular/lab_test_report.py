from ..base import DocumentFieldSchema, DocumentSchema
from ..object_core import ConfiguredObjectHandler, TRACKED_SIMPLE_DOCUMENT_FIELDS

LAB_TEST_REPORT_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a laboratory test report in English or Russian.
The text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the report
- `document_date` — the date of the report (normalize to DD/MM/YYYY when possible)
- `description` — the document title only, without numbers, dates, or identifiers, in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""


class LabTestReportHandler(ConfiguredObjectHandler):
    document_code = "11111"
    label = "Laboratory Test Report"
    prompt = LAB_TEST_REPORT_PROMPT
    examples = ()
    tracked_fields = TRACKED_SIMPLE_DOCUMENT_FIELDS
    empty_error = "No Laboratory Test Report fields extracted"

    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )
