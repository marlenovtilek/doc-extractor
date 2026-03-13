"""Compatibility wrapper for invoice-specific preprocessing helpers."""

from .documents.invoice import (
    _is_table_item_line,
    _table_cells,
    clean_text,
    extract_header,
    parse_full_doc_metadata,
    parse_header_metadata,
)
