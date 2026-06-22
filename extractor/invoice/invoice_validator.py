"""Invoice header-field extraction shared by the invoice pipeline."""

from typing import Any


def extract_header_fields(items: list[dict]) -> dict[str, Any]:
    """
    Extract header fields from invoice items.

    Fields: document_number, document_date, currency_code, currency_name, country_sender
    """
    fields = {
        "document_number": None,
        "document_date": None,
        "currency_code": None,
        "currency_name": None,
        "country_sender": None,
    }

    for item in items:
        for key in fields:
            if fields[key] is None:
                value = item.get(key)
                if value and str(value).strip().lower() not in ("none", "null", ""):
                    fields[key] = value

    return fields
